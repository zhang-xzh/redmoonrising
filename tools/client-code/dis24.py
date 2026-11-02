"""Minimal Python 2.4 bytecode disassembler for EVE client code objects."""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_OPCODE_SRC = os.path.join(_HERE, "opcode24.py")

opname = {}
opcode = {}
hasarg = set()
hasconst = set()
hasname = set()
hasjrel = set()
hasjabs = set()
haslocal = set()
hascompare = set()


def _load():
    g = {}
    exec(compile(open(_OPCODE_SRC, encoding="utf-8").read(), _OPCODE_SRC, "exec"), g)
    for name, code in g["opmap"].items():
        opname[code] = name
    global HAVE_ARGUMENT
    HAVE_ARGUMENT = g["HAVE_ARGUMENT"]
    for k, vals in (("hasconst", g["hasconst"]), ("hasname", g["hasname"]),
                    ("hasjrel", g["hasjrel"]), ("hasjabs", g["hasjabs"]),
                    ("haslocal", g["haslocal"]), ("hascompare", g["hascompare"])):
        target = {"hasconst": hasconst, "hasname": hasname, "hasjrel": hasjrel,
                  "hasjabs": hasjabs, "haslocal": haslocal,
                  "hascompare": hascompare}[k]
        target.update(vals)
def_op = None


_load()


def disassemble(co):
    code = bytes(co.code)
    consts = co.consts
    names = co.names
    varnames = co.varnames
    out = []
    i = 0
    while i < len(code):
        op = code[i]
        name = opname.get(op, "OP_%d" % op)
        arg = None
        if op >= HAVE_ARGUMENT:
            arg = code[i + 1] | (code[i + 2] << 8)
            i += 3
        else:
            i += 1
        val = ""
        if op in hasconst and arg is not None and arg < len(consts):
            val = _short(consts[arg])
        elif op in hasname and arg is not None and arg < len(names):
            val = names[arg].decode("latin1", "replace")
        elif op in haslocal and arg is not None and arg < len(varnames):
            val = varnames[arg].decode("latin1", "replace")
        elif op in hascompare and arg is not None:
            val = {0: "==", 1: "<", 2: ">", 3: "!=", 4: "in", 5: "not in",
                   6: "is", 7: "is not", 8: "exception match", 9: "BAD"}.get(arg, str(arg))
        out.append((i, name, arg, val))
    return out


def _short(v):
    if isinstance(v, bytes):
        try:
            return repr(v.decode("utf-8"))
        except Exception:
            return repr(v)
    if isinstance(v, str):
        return repr(v)
    if hasattr(v, "name"):
        return "<code %s>" % (v.name.decode("latin1", "replace"),)
    if isinstance(v, tuple):
        return "(" + ", ".join(_short(x) for x in v[:4]) + (", ...)" if len(v) > 4 else ")")
    if isinstance(v, list):
        return "[" + ", ".join(_short(x) for x in v[:4]) + "]"
    return repr(v)
