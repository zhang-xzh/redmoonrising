"""Ad-hoc scans over EVE 3913 `compiled.code` (read only)."""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eveccp, dis24

CCP = r"M:\EVE-LOCAL\inputs\EVE-Online-3913\script\compiled.code"


def modules():
    data = open(CCP, "rb").read()
    for path, (blob, aux) in eveccp.unpickle_container(data):
        yield path.decode("latin1"), eveccp.loads(blob), aux


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


def cmd_list():
    for i, (path, root, aux) in enumerate(modules()):
        print(i, path)


def cmd_grep(pat, where="all"):
    rx = re.compile(pat, re.I)
    for path, root, aux in modules():
        for p, co in walk(root, path):
            vals = []
            if where in ("all", "const"):
                flat(co.consts, vals)
            if where in ("all", "name"):
                vals = [v for v in vals if False]
                vals += list(co.names) + list(co.varnames) + list(co.cellvars) + list(co.freevars)
            hits = [v for v in vals if isinstance(v, bytes) and rx.search(v.decode("latin1"))]
            if hits:
                print("=== %s :: %s" % (path, p))
                for h in hits[:8]:
                    print("   ", h.decode("latin1")[:160])


def cmd_dis(target):
    for path, root, aux in modules():
        for p, co in walk(root, path):
            if p.endswith(target):
                print("=" * 100)
                print("MODULE", path, "FUNC", p, "flags", co.flags,
                      "argcount", co.argcount, "nlocals", co.nlocals)
                print("consts:", [dis24._short(c)[:100] for c in co.consts])
                print("names:", [n.decode("latin1", "replace") for n in co.names])
                for row in dis24.disassemble(co):
                    print("%5d  %-24s %5s  %s" % row)
                return
    print("not found:", target)


def cmd_tree(sub):
    for path, root, aux in modules():
        if sub not in path:
            continue
        for p, co in walk(root, path):
            print("%-80s %s" % (p, "" if co.flags & 0x02 else "<modbody>"))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print("usage: scan.py list | grep PAT [const|name|all] | dis <module-suffix/func> | tree <substr>")
        sys.exit(0)
    if a[0] == "list":
        cmd_list()
    elif a[0] == "grep":
        cmd_grep(a[1], a[2] if len(a) > 2 else "all")
    elif a[0] == "dis":
        cmd_dis(a[1])
    elif a[0] == "tree":
        cmd_tree(a[1])
