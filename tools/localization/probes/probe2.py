import json, re, sys
en = json.load(open(r"C:\Users\zhang\AppData\Local\Temp\opencode\loc_en.json", encoding="utf-8"))
zh = json.load(open(r"M:\EVE-LOCAL\EveJS\config\client_localization_fsd_zh.json", encoding="utf-8"))

def norm(s):
    s = s.replace("\x85", "...").replace("\u2026", "...")
    s = s.replace("\x92", "'").replace("\u2019", "'").replace("\x91", "'")
    s = s.replace("<br>", " ").replace("<b>", " ").replace("</b>", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def key(s):
    s = norm(s).lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s

count = 0
multi = 0
normmap = {}
for k, v in en.items():
    z = zh.get(k)
    if not (isinstance(v, str) and isinstance(z, str) and z.strip()):
        continue
    kk = key(v)
    if not kk:
        continue
    count += 1
    if kk in normmap and normmap[kk] != z:
        multi += 1
    normmap.setdefault(kk, z)
print("usable", count, "keys", len(normmap), "collisions", multi)

rev = {}
for v, k in ((v, k) for k, v in en.items() if isinstance(v, str)):
    pass

tests = ["Undock from Station", "Set new password", "View market details",
         "Add to market quickbar", "Sell this Item", "Buy this type", "Trash It",
         "Open Cargohold", "Ship Maintenance Bay", "Launch Ship", "Board Ship"]
for t in tests:
    print(repr(t), "->", normmap.get(key(t)))
