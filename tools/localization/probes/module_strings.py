import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eveccp

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
table = json.load(open(os.path.join(ROOT, "config", "localization", "ui_en_zh.json"), encoding="utf-8"))
data = open(r"M:\EVE-LOCAL\inputs\EVE-Online-3913\script\compiled.code", "rb").read()
items = [(p, v[0], v[1]) for (p, v) in eveccp.unpickle_container(data)]

for path, blob, aux in items:
    name = path.decode("latin1")
    if not any(k in name for k in sys.argv[1:]):
        continue
    root = eveccp.loads(blob)
    seen = []
    def walk(co):
        for c in co.consts:
            if isinstance(c, eveccp.Code):
                walk(c)
            elif isinstance(c, bytes):
                s = c.decode("latin1")
                if s in table:
                    seen.append((s, table[s]))
            elif isinstance(c, (tuple, list)):
                for x in c:
                    if isinstance(x, bytes):
                        s = x.decode("latin1")
                        if s in table:
                            seen.append((s, table[s]))
    walk(root)
    if seen:
        print("=" * 40, name)
        for s, z in seen[:40]:
            print("  ", repr(s), "->", z)
