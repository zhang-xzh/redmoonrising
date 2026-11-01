import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eveccp, dis24

CCP = r"M:\EVE-LOCAL\inputs\EVE-Online-3913\script\compiled.code"
TARGET = sys.argv[1] if len(sys.argv) > 1 else "Undock from Stations"

data = open(CCP, "rb").read()
items = [(p, v[0], v[1]) for (p, v) in eveccp.unpickle_container(data)]


def walk(co, path):
    yield path, co
    for c in co.consts:
        if isinstance(c, eveccp.Code):
            yield from walk(c, path + "/" + c.name.decode("latin1", "replace"))


def flat(v, out):
    if isinstance(v, (bytes, str)):
        out.append(v)
    elif isinstance(v, (tuple, list)):
        for x in v:
            flat(x, out)


for path, blob, aux in items:
    root = eveccp.loads(blob)
    for p, co in walk(root, path.decode("latin1", "replace")):
        vals = []
        flat(co.consts, vals)
        hits = [c for c in vals if TARGET in (c.decode("latin1", "replace") if isinstance(c, bytes) else c)]
        if not hits:
            continue
        print("=" * 100)
        print("MODULE", path.decode("latin1", "replace"), "FUNC", p, "flags", co.flags)
        print("consts:", [dis24._short(c) for c in co.consts])
        print("names:", [n.decode("latin1", "replace") for n in co.names])
        for row in dis24.disassemble(co):
            print("%4d  %-22s %5s  %s" % row)
        break
