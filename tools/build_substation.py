"""Fetch the SPEN open data for one SP Distribution primary substation and save it as a JS data file
for the explorer's substation headroom tour (loaded with a <script> tag, so it works from file:// and
on the published site without any key).

The SPEN open data portal only returns records to signed-in users, so this needs your (free) portal
API key, read from a file (first line). The key is sent in a request header via a temporary file,
never printed or put on the command line.

Data (all CC BY 4.0, SP Energy Networks open data portal, spenergynetworks.opendatasoft.com):
  distribution-capacity-heatmaps-spd    firm capacity, max/min demand, headroom, reverse power, contracted
  spd-ltds-appendix-3-system-loads-table-3   LTDS loads, forecasts and firm capacity (cross-check)
  historic_substation_demand_curve      median half-hourly demand by day of week, 2023–2025
  polygon_spd                           primary substation supply areas
  embedded-capacity-register            generation and storage, 1 MW and over
  embedded-capacity-register-50kv-1mw   generation and storage, 50 kW to 1 MW

Usage:
  python3 viewer/tools/build_substation.py --key-file spen_apikey.txt --substation Currie \
      --out viewer/data/substation_currie.js
  (add --list to print matching names in each dataset and stop)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse

BASE = "https://spenergynetworks.opendatasoft.com/api/explore/v2.1/catalog/datasets"

ap = argparse.ArgumentParser()
ap.add_argument("--key-file", required=True)
ap.add_argument("--substation", required=True, help="primary substation name, e.g. Currie")
ap.add_argument("--towns", default="", help="comma-separated towns for the 50 kW–1 MW register (its primary field is mostly blank)")
ap.add_argument("--out")
ap.add_argument("--list", action="store_true", help="only show which names match in each dataset")
args = ap.parse_args()

key = open(args.key_file).read().splitlines()[0].strip()
hdr = tempfile.NamedTemporaryFile("w", delete=False, prefix="spen_hdr_")
os.chmod(hdr.name, 0o600)
hdr.write(f"Authorization: Apikey {key}\n")
hdr.close()


def export(dataset, where=None, select=None):
    params = {"limit": "-1"}
    if where:
        params["where"] = where
    if select:
        params["select"] = select
    url = f"{BASE}/{dataset}/exports/json?" + urllib.parse.urlencode(params)
    out = subprocess.run(["curl", "-s", "-f", "-m", "180", "-H", f"@{hdr.name}", url], capture_output=True)
    if out.returncode != 0:
        sys.exit(f"{dataset}: request failed (curl exit {out.returncode}) — check the key and the dataset name")
    return json.loads(out.stdout or b"[]")


try:
    name = args.substation.strip()
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
    target = norm(name)
    text = name.replace('"', "")

    up = name.upper().replace('"', "")

    # exact "starts with" match on each dataset's substation field (e.g. CURRIE, CURRIE 11kV)
    def rows(dataset, field):
        got = export(dataset, where=f'startswith({field}, "{up}")')
        hits = [r for r in got if norm(r.get(field)).startswith(target)]
        names = sorted({str(r.get(field)) for r in hits})
        print(f"{dataset}: {len(hits)} rows for {names}")
        return hits

    heat = rows("distribution-capacity-heatmaps-spd", "name")
    ltds = rows("spd-ltds-appendix-3-system-loads-table-3", "substation")
    curve = rows("historic_substation_demand_curve", "asset_name")
    poly = rows("polygon_spd", "primary")
    ecr = rows("embedded-capacity-register", "primary")
    ecr_small = rows("embedded-capacity-register-50kv-1mw", "primary")
    # the small register mostly has no primary and no location, and some rows are shifted one column
    # to the right; take sites by town, straighten shifted rows, and drop exact repeats
    towns = [t.strip() for t in args.towns.split(",") if t.strip()]
    small_sites = []
    if towns:
        tl = ", ".join('"' + t.replace('"', "") + '"' for t in towns)
        raw = export("embedded-capacity-register-50kv-1mw", where=f"town_city in ({tl})")
        num = lambda v: float(v) if re.fullmatch(r"-?\d+(\.\d+)?", str(v or "").strip()) else None
        clean, shifted_rows = [], []
        for r in raw:
            shifted = str(r.get("country", "")).strip() not in ("Scotland", "England", "Wales")
            if shifted:   # values sit one field to the right; capacity there is in MW
                tech, status, cap = r.get("chp_cogeneration_yes_no"), r.get("already_connected_registered_capacity_kw"), num(r.get("energy_source_2"))
                kw = cap * 1000 if cap is not None and cap < 5 else cap
                date = r.get("target_energisation_date")
            else:
                tech, status = r.get("energy_conversion_technology_1"), r.get("connection_status")
                kw = num(r.get("energy_source_energy_conversion_technology_1_registered_capacity_kw"))
                date = r.get("date_connected") if re.match(r"\d{4}-", str(r.get("date_connected") or "")) else r.get("date_accepted")
            if kw is None or kw <= 0:
                continue
            site = {"town": r.get("town_city"), "tech": tech, "kw": round(kw, 1), "status": status,
                    "date": str(date)[:10] if re.match(r"\d{4}-", str(date or "")) else None,
                    "id": None if shifted else r.get("unique_id")}
            (shifted_rows if shifted else clean).append(site)
        ids = set()
        for site in clean:   # clean rows: one per unique id
            if site["id"] in ids:
                continue
            ids.add(site["id"]); small_sites.append(site)
        same = lambda a_, b_: (a_["town"], a_["kw"]) == (b_["town"], b_["kw"]) and \
            ("solar" in str(a_["tech"]).lower() or "photo" in str(a_["tech"]).lower()) == ("solar" in str(b_["tech"]).lower() or "photo" in str(b_["tech"]).lower())
        for site in shifted_rows:   # shifted rows: only if they aren't a repeat of a clean row
            if not any(same(site, c) for c in small_sites):
                small_sites.append(site)
        print(f"50 kW–1 MW register by town {towns}: {len(raw)} rows -> {len(small_sites)} sites after cleaning")
    if args.list:
        sys.exit(0)
    if not args.out:
        sys.exit("--out is needed (or use --list)")

    payload = {
        "substation": name,
        "source": "SP Energy Networks open data portal (CC BY 4.0)",
        "fetched": __import__("datetime").date.today().isoformat(),
        "heatmap": heat, "ltds": ltds, "demandCurve": curve, "polygon": poly,
        "ecr": ecr, "ecrSmall": ecr_small, "smallSitesByTown": small_sites, "towns": towns,
    }
    with open(args.out, "w") as fh:
        fh.write("// Generated by viewer/tools/build_substation.py — SPEN open data (CC BY 4.0) for one primary substation\n")
        fh.write("(window.SUBSTATIONS = window.SUBSTATIONS || {})[" + json.dumps(norm(name)) + "] = " +
                 json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ";\n")
    print(f"saved -> {args.out}")
finally:
    os.unlink(hdr.name)
