import sys, os, json, re, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import eveccp

CCP = r"M:\EVE-LOCAL\inputs\EVE-Online-3913\script\compiled.code"

def walk(co, path, out):
    out.append((path, co))
    for c in co.consts:
        if isinstance(c, eveccp.Code):
            walk(c, path + "/" + c.name.decode("latin1", "replace"), out)

def flat(v, out):
    if isinstance(v, (bytes, str)):
        out.append(v)
    elif isinstance(v, (tuple, list)):
        for x in v:
            flat(x, out)

def norm(s):
    s = s.replace("\x85", "...").replace("\u2026", "...")
    s = s.replace("\x92", "'").replace("\u2019", "'")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def key(s):
    s = norm(s).lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s

data = open(CCP, "rb").read()
items = [(p, v[0], v[1]) for (p, v) in eveccp.unpickle_container(data)]

occ = collections.Counter()
mods = collections.defaultdict(set)
for path, blob, aux in items:
    root = eveccp.loads(blob)
    calls = []
    walk(root, path.decode("latin1", "replace"), calls)
    for _, co in calls:
        vals = []
        flat(co.consts, vals)
        for v in vals:
            if isinstance(v, bytes):
                s = v.decode("latin1")
                occ[s] += 1
                mods[s].add(path.decode("latin1", "replace"))

en = json.load(open(r"C:\Users\zhang\AppData\Local\Temp\opencode\loc_en.json", encoding="utf-8"))
zh = json.load(open(r"M:\EVE-LOCAL\EveJS\config\client_localization_fsd_zh.json", encoding="utf-8"))

exact = {}
normmap = collections.defaultdict(collections.Counter)
for k, v in en.items():
    z = zh.get(k)
    if not (isinstance(v, str) and isinstance(z, str) and z.strip()):
        continue
    exact.setdefault(v, z)
    normmap[key(v)][z] += 1
print("en", len(en), "exact map", len(exact), "norm keys", len(normmap))

def lookup(s):
    if s in exact:
        return exact[s], "exact"
    k = key(s)
    c = normmap.get(k)
    if c:
        return c.most_common(1)[0][0], "norm"
    return None, None

matched = unmatched = 0
hit_occ = 0
cand = collections.Counter()
for s, c in occ.items():
    z, how = lookup(s)
    if z:
        matched += 1
        hit_occ += c
    else:
        unmatched += 1
        cand[s] += c
print("distinct", len(occ), "matched", matched, "unmatched", unmatched, "occ hit", hit_occ, "occ total", sum(occ.values()))

# candidate display strings: has space or starts with uppercase, ascii, len>=3, letters only-ish
def is_display(s):
    if any(ch < " " or ch > "~" for ch in s.replace("\x85", "")):
        return False
    if len(s) < 3:
        return False
    if not re.search(r"[A-Za-z]", s):
        return False
    if s.startswith("%") or "::" in s or s.startswith("res:/") or "script:/" in s:
        return False
    if re.match(r"^[a-z_][a-zA-Z0-9_]*$", s):
        return False
    words = s.split()
    if len(words) == 1 and not (s[0].isupper() and len(s) >= 4):
        return False
    return True

disp = [s for s in occ if is_display(s)]
dm = [s for s in disp if lookup(s)[0]]
print("display candidates", len(disp), "display matched", len(dm))
print("\n--- top unmatched display candidates ---")
for s, c in cand.most_common(400):
    if is_display(s):
        print(c, repr(s[:70]))
