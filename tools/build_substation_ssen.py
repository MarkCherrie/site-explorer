"""Build the substation headroom tour's data file for an SSEN primary from local SSEN open data (the
insights project's copies), in the same shape as build_substation.py writes for SPEN, so the explorer
treats both the same way.

Inputs (SSEN open data, CC BY 4.0, via opennetzero.org):
  --dashboard  SSEN network headroom dashboard CSV (one row per substation: location, transformer
               ratings, observed gross demand, contracted demand and generation, headroom, RAG,
               constraints, reinforcement works)
  --dfes       SSEN DFES 2025 by ESA (baseline installed generation by technology; scenarios for later)
  --lines-dir  folder holding the SHEPD "SSEN Overhead Lines" shapefiles (EHV, HV, LV)
  --shape-from a SPEN substation file from build_substation.py: its measured weekly demand shape is
               borrowed as a stand-in, because SSEN substation demand curves aren't available here
               (the page calibrates the level to this substation's own maximum and minimum)

Firm capacity is N-1 from the transformer nameplates ("2 x 12 / 24MVA" → one 24 MVA unit left).
SSEN doesn't publish a reverse power capacity here, so it is taken as equal to firm capacity (flagged).
Standby diesel is listed but left out of the hourly generation (it runs only when needed).

Usage:
  python3 viewer/tools/build_substation_ssen.py --dashboard ../insights/scripts/ssen_headroom_dashboard_2026-03.csv \
      --dfes ../insights/scripts/dfes/ssen_dfes_2025_esa_shepd.csv --lines-dir ../insights/scripts/ssen_network \
      --substation "Kirkwall Primary" --dfes-name KIRKWALL --shape-from viewer/data/substation_currie.js \
      --out viewer/data/substation_kirkwall.js
"""
import argparse
import csv
import glob
import json
import math
import os
import re
import subprocess
import tempfile

ap = argparse.ArgumentParser()
ap.add_argument("--dashboard", required=True)
ap.add_argument("--dfes", required=True)
ap.add_argument("--lines-dir")
ap.add_argument("--substation", required=True, help='dashboard name, e.g. "Kirkwall Primary"')
ap.add_argument("--dfes-name", required=True, help="DFES Primary_name, e.g. KIRKWALL")
ap.add_argument("--shape-from", required=True)
ap.add_argument("--half-km", type=float, default=7.0, help="half-width of the area around the substation, km")
ap.add_argument("--out", required=True)
args = ap.parse_args()

num = lambda v: float(v) if re.fullmatch(r"-?\d+(\.\d+)?", str(v or "").strip()) else None
row = next(r for r in csv.DictReader(open(args.dashboard, encoding="utf-8-sig")) if r["Substation"].strip() == args.substation)
lat, lon = float(row["Location Latitude"]), float(row["Location Longitude"])

# firm (N-1) capacity from the transformer nameplates: all units but the largest
units = []
for part in row["Transformer Nameplate Ratings"].split("+"):
    m = re.match(r"\s*(\d+)\s*x\s*([\d.]+)(?:\s*/\s*([\d.]+))?\s*MVA", part, re.I)
    if m:
        units += [float(m.group(3) or m.group(2))] * int(m.group(1))
single = row.get("Single Transformer Site", "").strip().lower() == "yes" or len(units) == 1
firm = (sum(units) - max(units)) if len(units) > 1 else (units[0] if units else None)

# baseline installed generation and storage by technology (DFES)
dfes = [r for r in csv.DictReader(open(args.dfes, encoding="utf-8-sig"))
        if r["Primary_name"] == args.dfes_name and r["Category"] in ("Generation", "Storage") and r["Units"] == "MW"]
seen, sites = set(), []
for r in dfes:   # baseline is the same in every scenario: take each technology once
    k = (r["Technology"], r["Subtechnology"])
    mw = num(r["Baseline"]) or 0
    if k in seen or mw <= 0:
        continue
    seen.add(k)
    tech = r["Technology"] + ("" if r["Subtechnology"] in ("-", "") else f" ({r['Subtechnology']})")
    standby = r["Technology"].lower() in ("diesel",)
    sites.append({"town": "DFES baseline", "tech": tech, "kw": round(mw * 1000, 1),
                  "status": "Standby" if standby else ("Storage" if r["Category"] == "Storage" else "Connected"), "date": None, "id": None})

# borrowed weekly demand shape (SPEN measured median, same field names as SPEN's curve)
src = open(args.shape_from).read()
proxy = json.loads(src.split("] = ", 1)[1].rstrip(";\n"))
curve = [{"asset_name": proxy["substation"].upper() + " (proxy)", "day_of_the_week": r["day_of_the_week"], "timestamp": r["timestamp"],
          "2025_demand_mw": r.get("2025_demand_mw"), "2024_demand_mw": r.get("2024_demand_mw"), "2023_demand_mw": r.get("2023_demand_mw")}
         for r in proxy["demandCurve"]]

# the area: a box around the substation
dlat = args.half_km / 110.57
dlon = args.half_km / (111.32 * math.cos(math.radians(lat)))
bounds = {"w": lon - dlon, "e": lon + dlon, "s": lat - dlat, "n": lat + dlat}

# overhead lines in the area (SHEPD shapefiles are British National Grid; GDAL reprojects and clips)
lines = []
if args.lines_dir:
    ogr = next((p for p in ["/opt/homebrew/Caskroom/miniforge/base/bin/ogr2ogr", "ogr2ogr"] if os.path.exists(p) or p == "ogr2ogr"))
    for shp in sorted(glob.glob(os.path.join(args.lines_dir, "*_shepd_zip", "*.shp"))):
        out = tempfile.NamedTemporaryFile(suffix=".geojson", delete=False).name
        os.unlink(out)
        subprocess.run([ogr, "-f", "GeoJSON", "-t_srs", "EPSG:4326", "-spat", str(bounds["w"]), str(bounds["s"]), str(bounds["e"]), str(bounds["n"]),
                        "-spat_srs", "EPSG:4326", "-lco", "COORDINATE_PRECISION=5", out, shp], check=True, capture_output=True)
        for f in json.load(open(out))["features"]:
            p, g = f["properties"], f["geometry"] or {}
            kv = 0.4 if "_lv_" in shp else num(re.sub(r"[^\d.]", "", str(p.get("nominal_vo") or "")))   # LV is tagged in volts
            parts = [g["coordinates"]] if g.get("type") == "LineString" else g.get("coordinates", []) if g.get("type") == "MultiLineString" else []
            for c in parts:
                if len(c) >= 2:
                    lines.append({"kv": kv, "src": os.path.basename(shp).split("_exi_")[1].split("_")[0].upper(), "coords": c})
        os.unlink(out)

heat = {   # SSEN figures under the SPEN field names the page already reads
    "name": args.substation.replace(" Primary", "").upper(), "type": row["Substation Type"], "area": "SHEPD",
    "longitude": lon, "latitude": lat, "voltage": row["Voltage (kV)"],
    "demandfirmcapacity": firm, "reversepowerflowtotalcapacity": firm,
    "demandmaximum": num(row["Maximum Observed Gross Demand (MVA)"]), "demandminimum": num(row["Minimum Observed Gross Demand (MVA)"]),
    "demandavailablecapacity": num(row["Estimated Demand Headroom (MVA)"]), "reversepowerflowavailablecapacity": num(row["Estimated Generation Headroom (MW)"]),
    "demandconstraint": row["Substation Demand RAG Status"], "generationconstraint": row["Substation Generation RAG Status"],
    "demandconstraintlimitingfactor": row["Demand Constraint"], "generationconstraintlimitingfactor": row["Generation Constraint"],
    "loadconnectionoffersacceptedcapacity": (num(row["Contracted Demand Excl BESS (MVA)"]) or 0) + (num(row["Contracted BESS Demand (MVA)"]) or 0),
    "generationconnectionofferacceptedcapacity": num(row["Contracted Generation (MW)"]),
    "connectedgeneration": num(row["Connected Generation (MW)"]),
}
notes = [
    f"Firm capacity is N-1 from the transformer nameplates ({row['Transformer Nameplate Ratings']})" + (" — single transformer site" if single else "") + ".",
    "Reverse power capacity isn't published in SSEN's dashboard; taken as equal to firm capacity.",
    f"Demand shape borrowed from SPEN's measured {proxy['substation']} weekly curve (SSEN substation curves not available here), calibrated to this substation's own maximum and minimum.",
    "Generation by technology from SSEN's DFES 2025 baseline; standby diesel isn't included in the hourly profile.",
]
if row.get("Upstream Reinforcement Works", "").strip():
    notes.append(f"Upstream works: {row['Upstream Reinforcement Works'].strip()} ({row.get('Upstream Reinforcement Completion Date', '').strip() or 'date not given'}).")

payload = {
    "substation": args.substation.replace(" Primary", ""), "dno": "SSEN", "sourceLabel": "SSEN headroom dashboard, DFES 2025",
    "source": "SSEN Distribution open data (CC BY 4.0), via opennetzero.org",
    "fetched": os.path.basename(args.dashboard),
    "heatmap": [heat], "ltds": [], "demandCurve": curve, "polygon": [], "ecr": [], "ecrSmall": [],
    "smallSitesByTown": sites, "towns": [], "bounds": bounds, "lines": lines, "notes": notes,
    "dashboard": {k: v for k, v in row.items() if v},
}
key = re.sub(r"[^a-z0-9]", "", payload["substation"].lower())
with open(args.out, "w") as fh:
    fh.write("// Generated by viewer/tools/build_substation_ssen.py — SSEN open data (CC BY 4.0) for one primary substation\n")
    fh.write(f"(window.SUBSTATIONS = window.SUBSTATIONS || {{}})[{json.dumps(key)}] = " + json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ";\n")
print(f"{args.substation}: firm {firm} MVA, {len(sites)} technologies, {len(lines)} line segments, {len(curve)} proxy shape rows -> {args.out}")
