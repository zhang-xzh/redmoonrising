"""Rewrite EVE 3913 client `compiled.code` display strings to Chinese.

Mapping: config/localization/ui_en_zh.json (built by build_map.py).

Design notes (learned from the client itself, build 3913):

* UI text rendering needs Python ``unicode``: the C++ label widget
  (xtriui.ULabel) and the Python glyph atlas code (fontsvc) both take
  per-character code points; byte strings would be split into UTF-8 bytes.
* The English client is not Python-2.3-unicode clean, so a constant may only
  be rewritten when it is *display text* and not also used as structural data.
  Structural uses we detect and skip:
    - class names (``class Foo:`` compiles to BUILD_CLASS(name, ...))
    - dict/index keys (LOAD_CONST immediately before BINARY/STORE_SUBSCR)
    - import names (IMPORT_NAME)
    - constants compared with COMPARE_OP
    - single-token identifiers (``Cargo``, ``ShipMaintenanceBay``, ``NULL``)
* Anything that still breaks is listed in ``exclude.json`` next to this file
  and skipped by exact string content.
"""
import sys, os, json, re
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "client-code"))
import eveccp, dis24

DEFAULT_MAP = os.path.join(ROOT, "config", "localization", "ui_en_zh.json")
DEFAULT_EXCLUDE = os.path.join(HERE, "exclude.json")

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def walk(co, out):
    out.append(co)
    for c in co.consts:
        if isinstance(c, eveccp.Code):
            walk(c, out)


def structural_consts(co):
    """Const indices used as class names / keys / import names / comparisons."""
    bad = set()
    rows = dis24.disassemble(co)
    for i, (off, name, arg, val) in enumerate(rows):
        if name == "COMPARE_OP" and i and rows[i - 1][1] == "LOAD_CONST":
            bad.add(rows[i - 1][2])
        elif name in ("BINARY_SUBSCR", "STORE_SUBSCR", "DELETE_SUBSCR") and i and rows[i - 1][1] == "LOAD_CONST":
            bad.add(rows[i - 1][2])
        elif name == "IMPORT_NAME" and i and rows[i - 1][1] == "LOAD_CONST":
            bad.add(rows[i - 1][2])
        elif name == "BUILD_CLASS":
            # LOAD_CONST name / BUILD_TUPLE / LOAD_CONST <code> / MAKE_FUNCTION /
            # CALL_FUNCTION / BUILD_CLASS
            j = i - 1
            while j >= 0 and rows[j][1] != "LOAD_CONST":
                j -= 1
            while j >= 0:
                if rows[j][1] == "LOAD_CONST" and isinstance(rows[j][3], str) and rows[j][3].startswith("'"):
                    bad.add(rows[j][2])
                    break
                j -= 1
    return bad


def usable(s):
    if len(s.strip()) < 2:
        return False
    if not re.search(r"[A-Za-z]", s):
        return False
    if s.startswith("res:/") or s.startswith("script:") or "::" in s:
        return False
    if re.search(r"[<>{}%\\]", s):
        return False
    if "=" in s or "\n" in s:
        return False
    # Single tokens are routinely reused as identifiers, dict keys, guid
    # prefixes and module names in this code base; only translate text that
    # reads like a phrase.
    if not re.search(r"\s", s.strip()):
        return False
    return True


def rewrite(value, table, stats):
    if isinstance(value, eveccp.BStr):
        s = bytes(value).decode("latin1")
        z = table.get(s)
        if z is not None and usable(s):
            stats["hit"].add(s)
            return eveccp.UStr(z)
        return value
    if isinstance(value, tuple):
        return tuple(rewrite(v, table, stats) for v in value)
    if isinstance(value, list):
        return [rewrite(v, table, stats) for v in value]
    return value


def process(src, dst, table, exclude, report=None):
    data = open(src, "rb").read()
    items = [(p, v[0], v[1]) for (p, v) in eveccp.unpickle_container(data)]
    out_items = []
    stats = {"hit": set(), "skipped": set()}
    modules = 0
    for path, blob, aux in items:
        root = eveccp.loads(blob)
        codes = []
        walk(root, codes)
        touched = False
        for co in codes:
            bad = structural_consts(co)
            consts = list(co.consts)
            changed = False
            for i, c in enumerate(consts):
                if i in bad:
                    continue
                new = rewrite(c, table, stats)
                if new is not c:
                    consts[i] = new
                    changed = True
            if changed:
                co.consts = tuple(consts)
                touched = True
        if touched:
            modules += 1
        out_items.append((path, eveccp.dumps(root), aux))
    open(dst, "wb").write(eveccp.pickle_container(out_items))
    if report:
        json.dump(sorted(stats["hit"]), open(report, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=0)
    return {"strings": len(stats["hit"]), "modules": modules}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--map", default=DEFAULT_MAP)
    ap.add_argument("--exclude", default=DEFAULT_EXCLUDE)
    ap.add_argument("--report")
    a = ap.parse_args()
    table = json.load(open(a.map, encoding="utf-8-sig"))
    if a.exclude and os.path.exists(a.exclude):
        for s in json.load(open(a.exclude, encoding="utf-8")):
            table.pop(s, None)
    st = process(a.src, a.dst, table, None, a.report)
    print("rewrote %d distinct strings in %d code objects" % (st["strings"], st["modules"]))
