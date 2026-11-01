import sys, os, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eveccp

MAP = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   "config", "localization", "ui_en_zh.json")
m = json.load(open(MAP, encoding="utf-8"))
print("map size", len(m))
for k in ["Username", "Password", "Log In", "Login", "Account", "Cancel", "Quit",
          "Undock from Station", "Jettison", "Open Cargohold", "Market", "Ship",
          "Corporation", "Station", "Wallet", "Inventory", "Skills", "Mail",
          "Manufacture", "Copy", "Research", "Select Character", "Create Character"]:
    print(repr(k), "->", repr(m.get(k)))

src = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\zhang\AppData\Local\Temp\opencode\compiled.code.zh"
data = open(src, "rb").read()
items = [(p, v[0], v[1]) for (p, v) in eveccp.unpickle_container(data)]
uni = 0
samples = []
for path, blob, aux in items:
    try:
        root = eveccp.loads(blob)
    except Exception as e:
        print("PARSE FAIL", path, e)
        continue
    def walk(co):
        global uni
        for c in co.consts:
            if isinstance(c, eveccp.UStr):
                uni += 1
                if len(samples) < 8:
                    samples.append(str(c))
            elif isinstance(c, eveccp.Code):
                walk(c)
    walk(root)
print("unicode consts", uni)
print("samples", samples)
