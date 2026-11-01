"""Round-trip check: every module in a compiled.code must re-serialise byte-exact.

    python verify.py --in <compiled.code>
    python verify.py --in <compiled.code.vanilla> --in <compiled.code.zh>

Prints one line per file: number of modules, pack/unpack ok, size.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eveccp


def check(path):
    data = open(path, "rb").read()
    items = [(p, v[0], v[1]) for (p, v) in eveccp.unpickle_container(data)]
    ok = bad = 0
    for name, blob, aux in items:
        try:
            if eveccp.dumps(eveccp.loads(blob)) == blob:
                ok += 1
            else:
                bad += 1
                print("  MISMATCH", name)
        except Exception as exc:
            bad += 1
            print("  ERROR", name, type(exc).__name__, exc)
    repacked = eveccp.pickle_container(items)
    print("%s: %d modules, roundtrip ok=%d bad=%d, size=%d, repack=%d" %
          (os.path.basename(path), len(items), ok, bad, len(data), len(repacked)))
    return bad == 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="files", action="append", required=True)
    a = ap.parse_args()
    good = True
    for f in a.files:
        good = check(f) and good
    sys.exit(0 if good else 1)
