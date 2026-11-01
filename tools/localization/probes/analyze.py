import sys, os, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eveccp

CCP = r"M:\EVE-LOCAL\inputs\EVE-Online-3913\script\compiled.code"

def walk(co, path, out):
    out.append((path, co))
    for c in co.consts:
        if isinstance(c, eveccp.Code):
            walk(c, path + "/" + c.name.decode("latin1"), out)

data = open(CCP, "rb").read()
items = [(p, v[0], v[1]) for (p, v) in eveccp.unpickle_container(data)]
strings = collections.Counter()
by_module = collections.Counter()
mods = []
for path, blob, aux in items:
    co = eveccp.loads(blob)
    flat = []
    walk(co, path.decode("latin1"), flat)
    mods.append((path.decode("latin1"), len(flat)))
    for _, c in flat:
        for k in c.consts:
            if isinstance(k, eveccp.BStr) and len(k) >= 1:
                strings[k] += 1
                by_module[path] += 1
print("modules", len(items), "code objects", sum(m[1] for m in mods), "distinct const strings", len(strings))

en = json.load(open(r"C:\Users\zhang\AppData\Local\Temp\opencode\loc_en.json", encoding="utf-8"))
zh = json.load(open(r"M:\EVE-LOCAL\EveJS\config\client_localization_fsd_zh.json", encoding="utf-8"))
print("en entries", len(en), "zh entries", len(zh))

# en -> set of zh
mapping = collections.defaultdict(list)
for k, v in en.items():
    z = zh.get(k)
    if z and v and isinstance(v, str) and isinstance(z, str):
        mapping[v].append(z)
print("en->zh distinct en", len(mapping))

matched = sum(c for s, c in strings.items() if s.decode("latin1", "replace") in mapping)
print("const strings matched (occurrences)", matched, "of", sum(strings.values()))
ms = sum(1 for s in strings if s.decode("latin1", "replace") in mapping)
print("distinct matched", ms, "of", len(strings))

# sample matched, prefer long text
samples = [(s.decode("latin1", "replace"), mapping[s.decode("latin1", "replace")][0]) for s in strings if s.decode("latin1", "replace") in mapping and len(s) > 3]
for s, z in samples[:25]:
    print(repr(s), "=>", z)
json.dump({s.decode("latin1", "replace"): strings[s] for s in strings}, open(r"C:\Users\zhang\AppData\Local\Temp\opencode\const_strings.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
