// Local relay for live ship positions from aisstream.io, for the Site explorer.
//
// aisstream.io doesn't allow connections straight from a web page, and the API key must stay off the
// page. This relay runs on your computer: it holds the key, keeps one connection to aisstream.io,
// and passes ship positions for the area you've rendered to the explorer over a local address.
//
// Setup (once):
//   1. Sign in at https://aisstream.io with GitHub and create an API key (Account page).
//   2. cd viewer/tools/ais-relay && npm install
// Run:
//   AISSTREAM_API_KEY=your-key node relay.mjs
//   or, with the key in a text file:  AISSTREAM_API_KEY_FILE=/path/to/apikey.txt node relay.mjs
// Then tick "Live ships" in the explorer (Options → Sea traffic). The relay listens on
// http://localhost:8787 by default (set PORT to change it).
//
// Only the explorer is allowed to read from the relay: pages opened from a file, from localhost, or
// from the origins in ALLOWED_ORIGINS (comma-separated; defaults to the published explorer).

import http from "node:http";
import WebSocket from "ws";

import fs from "node:fs";
// the key comes from AISSTREAM_API_KEY, or from a file named by AISSTREAM_API_KEY_FILE (first line)
const KEY = (process.env.AISSTREAM_API_KEY ||
  (process.env.AISSTREAM_API_KEY_FILE ? fs.readFileSync(process.env.AISSTREAM_API_KEY_FILE, "utf8").split(/\r?\n/)[0] : "")).trim();
const PORT = +(process.env.PORT || 8787);
const ALLOWED = (process.env.ALLOWED_ORIGINS || "https://markcherrie.github.io").split(",").map(s => s.trim()).filter(Boolean);
const UPSTREAM = "wss://stream.aisstream.io/v0/stream";
const TYPES = ["PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport", "ShipStaticData", "StaticDataReport"];
const STALE_MS = 30 * 60 * 1000;   // forget ships not heard from for 30 minutes
const DEBUG = !!process.env.DEBUG;   // DEBUG=1 prints a count of message types every 10 s
const seen = {};
if (DEBUG) setInterval(() => console.log("received:", JSON.stringify(seen)), 10_000);

if (!KEY) {
  console.error("Set AISSTREAM_API_KEY to your aisstream.io API key, e.g.\n  AISSTREAM_API_KEY=your-key node relay.mjs");
  process.exit(1);
}

// ---------------------------------------------------------------- ship state
const ships = new Map();   // mmsi → { mmsi, name, lat, lon, sog, cog, hdg, type, len, t }
function update(mmsi, patch) {
  const s = ships.get(mmsi) || { mmsi };
  Object.assign(s, patch);
  ships.set(mmsi, s);
  return s;
}
setInterval(() => {
  const cut = Date.now() - STALE_MS;
  for (const [k, s] of ships) if ((s.t || 0) < cut) ships.delete(k);
}, 60_000);

// ---------------------------------------------------------------- clients (server-sent events)
const clients = new Set();   // { res, box: [s, w, n, e] }
const inBox = (s, b) => Number.isFinite(s.lat) && s.lat >= b[0] && s.lat <= b[2] && s.lon >= b[1] && s.lon <= b[3];
function send(c, event, data) { c.res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`); }

const server = http.createServer((req, res) => {
  const origin = req.headers.origin;
  const ok = !origin || origin === "null" || /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin) || ALLOWED.includes(origin);
  if (!ok) { res.writeHead(403); res.end("origin not allowed"); return; }
  const cors = origin ? { "Access-Control-Allow-Origin": origin, "Vary": "Origin" } : {};
  const url = new URL(req.url, "http://localhost");
  if (url.pathname === "/health") {
    res.writeHead(200, { "Content-Type": "application/json", ...cors });
    res.end(JSON.stringify({ upstream: upstreamState, ships: ships.size, clients: clients.size }));
    return;
  }
  if (url.pathname !== "/ships") { res.writeHead(404, cors); res.end(); return; }
  const box = (url.searchParams.get("bbox") || "").split(",").map(Number);   // south,west,north,east
  if (box.length !== 4 || box.some(v => !Number.isFinite(v)) || box[0] >= box[2] || box[1] >= box[3]) {
    res.writeHead(400, cors); res.end("bbox=south,west,north,east"); return;
  }
  res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", "Connection": "keep-alive", ...cors });
  const c = { res, box };
  clients.add(c);
  send(c, "status", { upstream: upstreamState });
  send(c, "snapshot", [...ships.values()].filter(s => inBox(s, box)));   // ships already known in this area
  const ping = setInterval(() => res.write(": keepalive\n\n"), 20_000);
  req.on("close", () => { clearInterval(ping); clients.delete(c); resubscribe(); });
  resubscribe();
  console.log(`client connected for ${box.join(", ")} (${clients.size} open)`);
});

// ---------------------------------------------------------------- upstream (aisstream.io)
let ws = null, upstreamState = "connecting", retry = 1000, lastSub = 0, subTimer = null;
function boxes() {   // the union of what the open pages want ([[lat, lon], [lat, lon]] corners)
  const list = [...clients].map(c => [[c.box[0], c.box[1]], [c.box[2], c.box[3]]]);
  return list.length ? list : [[[0, 0], [0.001, 0.001]]];   // keep the connection alive with a tiny box when idle
}
function subscribe() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ APIKey: KEY, BoundingBoxes: boxes(), FilterMessageTypes: TYPES }));
  lastSub = Date.now();
}
function resubscribe() {   // aisstream.io allows at most one subscription update per second
  clearTimeout(subTimer);
  subTimer = setTimeout(subscribe, Math.max(0, 1100 - (Date.now() - lastSub)));
}
function broadcast(event, s) {
  for (const c of clients) if (event !== "ship" || inBox(s, c.box)) send(c, event, s);
}
function connect() {
  ws = new WebSocket(UPSTREAM, { perMessageDeflate: true });
  ws.on("open", () => { upstreamState = "open"; retry = 1000; subscribe(); broadcast("status", { upstream: upstreamState }); console.log("connected to aisstream.io"); });
  ws.on("message", buf => {
    let m;
    try { m = JSON.parse(buf.toString()); } catch { return; }
    if (DEBUG) { seen[m.MessageType] = (seen[m.MessageType] || 0) + 1; }
    if (m.error) { console.error("aisstream.io:", m.error); broadcast("status", { upstream: "error", error: String(m.error) }); return; }
    const md = m.MetaData || {}, type = m.MessageType, body = (m.Message || {})[type] || {};
    const mmsi = md.MMSI || body.UserID;
    if (!mmsi) return;
    const lat = md.latitude ?? md.Latitude ?? body.Latitude, lon = md.longitude ?? md.Longitude ?? body.Longitude;
    const name = (md.ShipName || body.Name || "").trim() || undefined;
    let s;
    if (/PositionReport$/.test(type)) {
      if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return;
      const patch = { lat, lon, sog: body.Sog, cog: body.Cog, hdg: body.TrueHeading, t: Date.now() };
      if (name) patch.name = name;
      if (type === "ExtendedClassBPositionReport") Object.assign(patch, staticPatch(body));
      s = update(mmsi, patch);
    } else if (type === "ShipStaticData") {
      s = update(mmsi, { ...(name ? { name } : {}), ...staticPatch(body), dest: (body.Destination || "").trim() || undefined });
    } else if (type === "StaticDataReport") {
      const a = body.ReportA || {}, b = body.ReportB || {};
      s = update(mmsi, { ...(a.Valid && a.Name ? { name: a.Name.trim() } : {}), ...(b.Valid ? staticPatch(b) : {}) });
    } else return;
    if (Number.isFinite(s.lat)) broadcast("ship", s);
  });
  ws.on("close", (code, reason) => {
    upstreamState = "reconnecting";
    broadcast("status", { upstream: upstreamState });
    console.log(`aisstream.io closed (${code} ${reason || ""}); retrying in ${retry / 1000}s`);
    setTimeout(connect, retry);
    retry = Math.min(60_000, retry * 2);
  });
  ws.on("error", err => console.error("aisstream.io:", err.message));
}
function staticPatch(b) {
  const d = b.Dimension || {}, len = (d.A || 0) + (d.B || 0);
  const out = {};
  const type = b.Type ?? b.ShipType;
  if (Number.isFinite(type) && type > 0) out.type = type;
  if (len > 0) out.len = len;
  return out;
}

server.listen(PORT, "127.0.0.1", () => {
  console.log(`Site explorer ship relay on http://localhost:${PORT}  (allowed sites: file pages, localhost, ${ALLOWED.join(", ")})`);
  connect();
});
