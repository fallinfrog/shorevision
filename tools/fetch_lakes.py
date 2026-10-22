"""Download lake/pond outlines and fishing access points from OpenStreetMap
(Overpass API) for each region in tools/regions.json and write a compact
data/<id>.json the app can load without hitting the live servers.
Map data (c) OpenStreetMap contributors, ODbL."""
import json, math, time, urllib.parse, urllib.request, datetime, sys, os

EPS = ["https://overpass-api.de/api/interpreter",
       "https://overpass.private.coffee/api/interpreter",
       "https://overpass.kumi.systems/api/interpreter",
       "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
NOTRIV = '["water"!~"^(river|stream|canal|ditch|drain|rapids|lock|oxbow|wastewater)$"]'

def overpass(q):
    last = None
    for attempt in range(3):
        for ep in EPS:
            try:
                req = urllib.request.Request(ep, data=urllib.parse.urlencode({"data": q}).encode(),
                                             headers={"User-Agent": "ShoreVision data build (github.com/fallinfrog/shorevision)"})
                with urllib.request.urlopen(req, timeout=300) as r:
                    j = json.load(r)
                if "elements" in j:
                    return j
            except Exception as e:  # try next mirror
                last = e
                print("  ", ep, "failed:", e, file=sys.stderr)
        time.sleep(20)
    raise RuntimeError(f"all Overpass mirrors failed: {last}")

def area_m2(g):
    if len(g) < 4: return 0
    lat0 = g[0]["lat"]; k = math.cos(math.radians(lat0)) * 111320
    pts = [((p["lon"]) * k, p["lat"] * 110540) for p in g]
    a = 0
    for i in range(len(pts) - 1):
        a += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
    return abs(a) / 2

def pack(g):  # flat [lat,lon,lat,lon,...] at ~1 m precision
    out = []
    for p in g:
        out += [round(p["lat"], 5), round(p["lon"], 5)]
    return out

def build(region):
    s, w, n, e = region["bbox"]
    bb = f"{s},{w},{n},{e}"
    water = overpass(f'[out:json][timeout:240];(way["natural"="water"]{NOTRIV}({bb});relation["natural"="water"]{NOTRIV}({bb});way["landuse"="reservoir"]({bb});relation["landuse"="reservoir"]({bb}););out geom;')
    access = overpass(f'[out:json][timeout:120];(nwr["leisure"~"^(fishing|slipway)$"]({bb});nwr["man_made"="pier"]({bb});nwr["waterway"="dam"]({bb}););out center tags;')
    from collections import Counter
    print("  raw:", Counter(el["type"] for el in water["elements"]),
          "relations with member geometry:", sum(1 for el in water["elements"] if el["type"] == "relation" and any(m.get("geometry") for m in el.get("members", []))))
    keep_tags = ("name", "natural", "water", "landuse")
    W = []
    for el in water["elements"]:
        tags = {k: v for k, v in (el.get("tags") or {}).items() if k in keep_tags}
        if el["type"] == "way" and el.get("geometry"):
            g = el["geometry"]
            if area_m2(g) < 1500:  # skip puddles under ~0.4 acre
                continue
            W.append({"t": "w", "id": el["id"], "tags": tags, "g": pack(g)})
        elif el["type"] == "relation":
            mem = [{"r": m.get("role", "outer"), "g": pack(m["geometry"])}
                   for m in el.get("members", []) if m.get("type") == "way" and m.get("geometry")]
            if mem:
                W.append({"t": "r", "id": el["id"], "tags": tags, "m": mem})
    A = []
    for el in access["elements"]:
        c = (el.get("lat"), el.get("lon")) if el["type"] == "node" else ((el.get("center") or {}).get("lat"), (el.get("center") or {}).get("lon"))
        if c[0] is None: continue
        tags = {k: v for k, v in (el.get("tags") or {}).items() if k in ("name", "leisure", "man_made", "waterway")}
        A.append({"lat": round(c[0], 6), "lon": round(c[1], 6), "tags": tags})
    stats = {"raw_" + k: v for k, v in Counter(el["type"] for el in water["elements"]).items()}
    stats["raw_relations_named"] = sorted({(el.get("tags") or {}).get("name", "?") for el in water["elements"] if el["type"] == "relation"})[:50]
    out = {"stats": stats, "region": region, "built": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
           "attribution": "Map data (c) OpenStreetMap contributors, ODbL", "water": W, "access": A}
    os.makedirs("data", exist_ok=True)
    path = f"data/{region['id']}.json"
    with open(path, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"{region['id']}: {len(W)} water bodies, {len(A)} access points, {os.path.getsize(path)//1024} KB")

if __name__ == "__main__":
    regions = json.load(open("tools/regions.json"))
    for r in regions:
        build(r)
    json.dump([{"id": r["id"], "name": r["name"], "bbox": r["bbox"]} for r in regions],
              open("data/regions.json", "w"), separators=(",", ":"))
