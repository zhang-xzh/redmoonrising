"""Build ui_en_zh.json: old client const strings -> Chinese.

Inputs:
  --en    messageID -> English, dumped from the retail 3396210 client
          (tools/FsdDump/dump_localization.py --lang en-us)
  --zh    messageID -> Chinese, same client
          (EveJS: config/client_localization_fsd_zh.json)
  --client compiled.code to scan for English constants (default: the 3913 build)

Matching: exact English, then a punctuation/case-insensitive key.  Placeholders
must match so %-formatting in the old client keeps working.
"""
import sys, os, json, re, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eveccp

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ui_en_zh.json")

CCP = r"M:\EVE-LOCAL\inputs\EVE-Online-3913\script\compiled.code"
EN_JSON = os.environ.get("RMR_LOC_EN") or os.path.join(
    os.environ.get("TEMP", "."), "opencode", "loc_en.json")
ZH_JSON = r"M:\EVE-LOCAL\EveJS\config\client_localization_fsd_zh.json"

PLACEHOLDER = re.compile(r"%(?:\([^)]*\))?[-+ #0-9.*hlL]*[diouxXeEfFgGcrs%]")


def norm(s):
    s = s.replace("\x85", "...").replace("\u2026", "...")
    s = s.replace("\x91", "'").replace("\x92", "'")
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = s.replace("<br>", " ").replace("<b>", " ").replace("</b>", " ")
    return re.sub(r"\s+", " ", s).strip()


def key(s):
    return re.sub(r"[^a-z0-9]+", "", norm(s).lower())


def placeholders(s):
    return sorted(PLACEHOLDER.findall(s))


def walk(co, out):
    out.append(co)
    for c in co.consts:
        if isinstance(c, eveccp.Code):
            walk(c, out)


def flat(v, out):
    if isinstance(v, bytes):
        out.append(v)
    elif isinstance(v, (tuple, list)):
        for x in v:
            flat(x, out)


def usable(s):
    if len(norm(s)) < 2:
        return False
    if not re.search(r"[A-Za-z]", s):
        return False
    if s.startswith("res:/") or s.startswith("script:") or "::" in s:
        return False
    # markup / format tokens must never be rewritten
    if re.search(r"[<>{}%\\]", s):
        return False
    if "=" in s:
        return False
    # lowercase single words are identifiers / logic keys in this client
    if re.fullmatch(r"[a-z_][a-z0-9_]*", s):
        return False
    if re.fullmatch(r"[a-z][a-zA-Z0-9_]*", s):
        return False
    return True


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--en", default=EN_JSON, help="messageID -> English (3396210 dump)")
    ap.add_argument("--zh", default=ZH_JSON, help="messageID -> Chinese")
    ap.add_argument("--client", default=CCP, help="compiled.code to scan for constants")
    ap.add_argument("--out", default=OUT, help="output json")
    a = ap.parse_args()

    en = json.load(open(a.en, encoding="utf-8"))
    zh = json.load(open(a.zh, encoding="utf-8"))
    exact = {}
    fuzzy = collections.defaultdict(collections.Counter)
    for mid, text in en.items():
        z = zh.get(mid)
        if not (isinstance(text, str) and isinstance(z, str) and z.strip() and text.strip()):
            continue
        exact.setdefault(text, z)
        k = key(text)
        if k:
            fuzzy[k][z] += 1

    data = open(a.client, "rb").read()
    items = [(p, v[0], v[1]) for (p, v) in eveccp.unpickle_container(data)]
    strings = set()
    for path, blob, aux in items:
        root = eveccp.loads(blob)
        codes = []
        walk(root, codes)
        for co in codes:
            vals = []
            flat(co.consts, vals)
            for v in vals:
                strings.add(bytes(v).decode("latin1"))

    result = {}
    ambiguous = 0
    for s in strings:
        if not usable(s):
            continue
        z = exact.get(s)
        if z is None:
            c = fuzzy.get(key(s))
            if c:
                z = c.most_common(1)[0][0]
                if len(c) > 1:
                    ambiguous += 1
        if z is None or not z.strip() or z == s:
            continue
        if re.search(r"[<>{}]", z):
            continue
        if placeholders(z) != placeholders(s):
            continue
        result[s] = z

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(result, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("strings seen", len(strings), "translated", len(result), "ambiguous picks", ambiguous)
    print("->", a.out)


if __name__ == "__main__":
    main()
