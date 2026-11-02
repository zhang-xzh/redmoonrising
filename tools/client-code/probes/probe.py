import json, sys
en = json.load(open(r"C:\Users\zhang\AppData\Local\Temp\opencode\loc_en.json", encoding="utf-8"))
zh = json.load(open(r"M:\EVE-LOCAL\EveJS\config\client_localization_fsd_zh.json", encoding="utf-8"))
rev = {}
for k, v in en.items():
    if isinstance(v, str):
        rev.setdefault(v, []).append(k)
tests = ["Undock from Station", "Jettison", "Open Cargohold", "Ship Maintenance Bay",
         "Launch Ship", "Board Ship", "Set new password", "Manufacture", "Copy",
         "Trash It", "Set Name", "Repackaged", "Open Container", "View market details",
         "Add to market quickbar", "Sell this Item", "Buy this type", "Make Active"]
for t in tests:
    ids = rev.get(t)
    if ids:
        print(repr(t), "->", [zh.get(i) for i in ids[:3]])
    else:
        # fuzzy: startswith
        cand = [k for k in rev if t.lower() in k.lower()][:5]
        print(repr(t), "MISS", cand)
