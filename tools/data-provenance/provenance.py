#!/usr/bin/env python3
"""Provenance checks for the 3913 client and the RMR database (read-only).

The retail 3913 client carries no static game data; `db/*.sql.gz` is a
PostgreSQL dump of a 2006-era server database, not an official SDE, and it
has no build/version column.  This tool records what can be verified:

* `manifest` - sha256 manifest of the client install and the db dumps, so a
  reset/reinstall or a silent edit is detectable later.
* `snapshot` - row counts, content markers and the `eveMessages` key list,
  parsed straight out of `db/*.sql.gz` (no Postgres needed).
* `client-keys` - message keys referenced by `script/compiled.code`
  (`eve.Message('Key')`, `cfg.GetMessage('Key')`, `mls.KEY`), extracted from
  the bytecode, not from the decompiled tree.
* `check` - cross-check client message keys against `messages.txt` and the
  database snapshot: keys the client asks for but neither source defines are
  data/client drift.

Typical use::

    PY=C:/Users/.../python.exe
    & $PY provenance.py manifest --out manifest-3913.json
    & $PY provenance.py snapshot --out db-snapshot-3913.json
    & $PY provenance.py check --snapshot db-snapshot-3913.json

Only `manifest` needs the client install; `snapshot`/`check` also work on a
copy of the repo alone (client-keys needs `script/compiled.code`).
"""
import argparse
import gzip
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tools", "localization"))

DEFAULT_CLIENT = r"M:\EVE-LOCAL\inputs\EVE-Online-3913"
DEFAULT_DB = os.path.join(REPO, "db")

SKIP_DIRS = {"cache", "logs", "capture", "stdlib"}
CLIENT_TOP_FILES = ("boot.ini", "eve.exe")
CLIENT_DIRS = ("script", "res", "bin", "lib")

KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:]*$")

COUNT_TABLES = ("invTypes", "invGroups", "invCategories", "dgmAttributeTypes",
                "dgmEffects", "invBlueprintTypes", "mapSolarSystems", "mapRegions",
                "staStations", "agtAgents", "eveMessages", "ramActivities")

WANTED = {"eveMessages", "invGroups", "invTypes", "ramActivities", "mapSolarSystems"}

CAPITAL_GROUPS = {"Titan", "Dreadnought", "Carrier"}
TITAN_TYPES = {"Avatar", "Erebus", "Leviathan", "Naglfar"}
COMMAND_SHIPS = {"Absolution", "Astarte", "Damnation", "Eos", "Nighthawk", "Vulture",
                 "Claymore", "Sleipnir"}
MARAUDERS = {"Golem", "Paladin", "Vargur", "Kronos"}
BLACKOPS = {"Widow", "Panther", "Redeemer", "Sin"}
JUMP_FREIGHTERS = {"Anshar", "Ark", "Nomad", "Rhea"}
T3 = {"Tengu", "Legion", "Proteus", "Loki"}
ORCA_RORQUAL = {"Orca", "Rorqual"}

COPY_RE = re.compile(r'^COPY\s+(?:"?public"?\.)?"?([A-Za-z0-9_]+)"?\s*'
                     r'(?:\((.*?)\))?\s+FROM stdin;\s*$')


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_entries(client, dbroot):
    out = []
    for name in CLIENT_TOP_FILES:
        p = os.path.join(client, name)
        if os.path.isfile(p):
            out.append(("client/" + name, p))
    for name in CLIENT_DIRS:
        root = os.path.join(client, name)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for fn in sorted(filenames):
                p = os.path.join(dirpath, fn)
                rel = os.path.relpath(p, client).replace(os.sep, "/")
                out.append(("client/" + rel, p))
    # resource archives sit next to the install, not under res/
    for fn in sorted(os.listdir(client)):
        if fn.endswith(".stuff"):
            out.append(("client/" + fn, os.path.join(client, fn)))
    for fn in sorted(os.listdir(dbroot)):
        if fn.endswith(".sql.gz"):
            out.append(("db/" + fn, os.path.join(dbroot, fn)))
    return out


def cmd_manifest(a):
    if a.verify:
        data = json.load(open(a.verify, encoding="utf-8"))
        # The recorded paths are informational only: verify against this
        # checkout/install unless the caller overrides them.
        client = a.client or DEFAULT_CLIENT
        dbroot = a.db or DEFAULT_DB
        bad = []
        for rec in data["files"]:
            p = os.path.join(client if rec["group"] == "client" else dbroot,
                             rec["path"].split("/", 1)[1])
            if not os.path.isfile(p):
                bad.append((rec["path"], "missing"))
                continue
            if os.path.getsize(p) != rec["size"]:
                bad.append((rec["path"], "size %d != %d" % (os.path.getsize(p), rec["size"])))
                continue
            digest = sha256_file(p)
            if digest != rec["sha256"]:
                bad.append((rec["path"], "sha256 mismatch"))
        print("manifest: %d files, %d problem(s)" % (len(data["files"]), len(bad)))
        for path, why in bad:
            print("  %-60s %s" % (path, why))
        return 1 if bad else 0

    client = a.client or DEFAULT_CLIENT
    dbroot = a.db or DEFAULT_DB
    files = []
    for label, path in manifest_entries(client, dbroot):
        group, rel = label.split("/", 1)
        files.append({"group": group, "path": label, "size": os.path.getsize(path),
                      "sha256": sha256_file(path)})
    data = {"client": client,
            "db": (os.path.relpath(dbroot, REPO).replace(os.sep, "/")
                   if os.path.abspath(dbroot).startswith(os.path.abspath(REPO))
                   else dbroot),
            "files": files}
    text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    if a.out:
        open(a.out, "w", encoding="utf-8", newline="\n").write(text)
        print("wrote %s (%d files)" % (a.out, len(files)))
    else:
        sys.stdout.write(text)
    return 0


def scan_dumps(dbroot):
    """Read `db/*.sql.gz` and return ({table: rowcount}, {table: (columns, rows)})."""
    counts = {}
    data = {}
    for fn in sorted(os.listdir(dbroot)):
        if not fn.endswith(".sql.gz"):
            continue
        current = None  # (table, columns, rows-or-None)
        with gzip.open(os.path.join(dbroot, fn), "rt", encoding="utf-8",
                       errors="replace") as fh:
            for line in fh:
                if line.startswith("COPY "):
                    m = COPY_RE.match(line.rstrip("\n"))
                    if not m:
                        current = None
                        continue
                    table = m.group(1)
                    cols = None
                    if m.group(2):
                        cols = [c.strip().strip('"') for c in m.group(2).split(",")]
                    counts[table] = 0
                    rows = [] if table in WANTED else None
                    if rows is not None:
                        data[table] = (cols, rows)
                    current = (table, cols, rows)
                    continue
                if current is None:
                    continue
                if line.startswith("\\."):
                    current = None
                    continue
                counts[current[0]] += 1
                if current[2] is not None:
                    current[2].append(line.rstrip("\n").split("\t"))
    for table in list(data):
        if data[table][0] is None:
            del data[table]
    return counts, data


def col(columns, name, default=None):
    if columns and name in columns:
        return columns.index(name)
    return default


def names_in(rows, columns, column, wanted):
    idx = col(columns, column)
    if idx is None:
        return 0
    return sum(1 for r in rows if len(r) > idx and r[idx] in wanted)


def max_int(rows, columns, column):
    idx = col(columns, column)
    if idx is None:
        return None
    values = []
    for r in rows:
        if len(r) > idx and r[idx]:
            try:
                values.append(int(r[idx]))
            except ValueError:
                pass
    return max(values) if values else None


def cmd_snapshot(a):
    dbroot = a.db or DEFAULT_DB
    counts, data = scan_dumps(dbroot)
    messages = data.get("eveMessages", (None, []))[1]
    msg_cols = data.get("eveMessages", (None, []))[0]
    midx = col(msg_cols, "messageID", 0)
    message_ids = sorted(r[midx] for r in messages if len(r) > midx)

    groups = data.get("invGroups", (None, []))
    types = data.get("invTypes", (None, []))
    systems = data.get("mapSolarSystems", (None, []))
    acts = data.get("ramActivities", (None, []))

    act_cols = acts[0]
    act_idx = col(act_cols, "activityName")
    inventions = sum(1 for r in acts[1] if act_idx is not None and len(r) > act_idx
                     and r[act_idx] == "Invention")

    g_idx = col(groups[0], "groupName")
    rig_groups = 0
    if g_idx is not None:
        rig_groups = sum(1 for r in groups[1] if len(r) > g_idx
                         and "rig" in r[g_idx].lower() and "frigate" not in r[g_idx].lower())

    markers = {
        "capital_groups": names_in(groups[1], groups[0], "groupName", CAPITAL_GROUPS),
        "titan_types": names_in(types[1], types[0], "typeName", TITAN_TYPES),
        "command_ships": names_in(types[1], types[0], "typeName", COMMAND_SHIPS),
        "rig_groups": rig_groups,
        "marauder_types": names_in(types[1], types[0], "typeName", MARAUDERS),
        "blackops_types": names_in(types[1], types[0], "typeName", BLACKOPS),
        "jumpfreighter_types": names_in(types[1], types[0], "typeName", JUMP_FREIGHTERS),
        "t3_types": names_in(types[1], types[0], "typeName", T3),
        "orca_rorqual": names_in(types[1], types[0], "typeName", ORCA_RORQUAL),
        "contract_tables": sum(1 for t in counts if t.lower().startswith("contract")),
        "invention_activity": inventions,
        "max_type_id": max_int(types[1], types[0], "typeID"),
        "max_solar_system_id": max_int(systems[1], systems[0], "solarSystemID"),
    }
    table_counts = {t: counts.get(t, 0) for t in COUNT_TABLES}
    missing = sorted(t for t in COUNT_TABLES if t not in counts)

    snapshot = {
        "counts": table_counts,
        "missing_tables": missing,
        "markers": markers,
        "messages": message_ids,
        "activities": ["%s|%s" % (r[0], r[1]) for r in acts[1] if len(r) > 1],
    }
    text = json.dumps(snapshot, indent=1, ensure_ascii=False) + "\n"
    if a.out:
        open(a.out, "w", encoding="utf-8", newline="\n").write(text)
        print("wrote %s (%d messages)" % (a.out, len(message_ids)))
    else:
        sys.stdout.write(text)
    return 0


def walk_code(co, out):
    import eveccp
    out.append(co)
    for c in co.consts:
        if isinstance(c, eveccp.Code):
            walk_code(c, out)


def client_message_keys(path):
    """{key: set(module paths)} extracted from bytecode."""
    import eveccp
    import dis24

    raw = open(path, "rb").read()
    hits = {}
    for module_path, (blob, _aux) in eveccp.unpickle_container(raw):
        mod = module_path.decode("latin1")
        root = eveccp.loads(blob)
        codes = []
        walk_code(root, codes)
        for co in codes:
            rows = dis24.disassemble(co)
            for i, (_off, name, arg, val) in enumerate(rows):
                if name == "LOAD_ATTR" and val in ("Message", "GetMessage"):
                    prev = rows[i - 1] if i else None
                    if not (prev and prev[1] in ("LOAD_GLOBAL", "LOAD_NAME")
                            and prev[3] in ("eve", "cfg")):
                        continue
                    # the key is the first positional argument: LOAD_CONST must
                    # directly follow the attribute load.  `eve.Message(msgName,
                    # {...})` and `GetMessage(..., onNotFound='raise')` are not
                    # constant keys and must not be picked up.
                    if i + 1 >= len(rows) or rows[i + 1][1] != "LOAD_CONST":
                        continue
                    idx = rows[i + 1][2]
                    if idx is None or idx >= len(co.consts):
                        continue
                    # `eve.Message('NeoCom' + action)` builds the key at runtime;
                    # only take plain constant keys (a string op before the call
                    # means the argument is computed).
                    dynamic = False
                    for j in range(i + 2, min(i + 8, len(rows))):
                        if rows[j][1] in ("CALL_FUNCTION", "CALL_FUNCTION_KW",
                                          "CALL_FUNCTION_VAR", "CALL_FUNCTION_VAR_KW"):
                            break
                        if rows[j][1] in ("BINARY_ADD", "INPLACE_ADD", "BINARY_MODULO"):
                            dynamic = True
                            break
                    if dynamic:
                        continue
                    value = co.consts[idx]
                    if isinstance(value, bytes):
                        value = value.decode("latin1", "replace")
                    if isinstance(value, str) and KEY_RE.match(value):
                        hits.setdefault(value, set()).add(mod)
                elif name in ("LOAD_GLOBAL", "LOAD_NAME") and val == "mls":
                    for j in range(i + 1, min(i + 4, len(rows))):
                        if rows[j][1] == "LOAD_ATTR" and KEY_RE.match(rows[j][3] or ""):
                            key = rows[j][3]
                            # real attributes of mlsUtil.Mls, not message keys
                            if key not in ("langPacks", "TR", "LoadLanguagePack"):
                                hits.setdefault(key, set()).add(mod)
                            break
    return hits


def parse_messages_txt(path):
    keys = set()
    if not os.path.isfile(path):
        return keys
    raw = open(path, "rb").read()
    if raw[:2] == b"\xff\xfe":
        text = raw.decode("utf-16")
    else:
        text = raw.decode("latin1")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if "." in key:
            key = key.split(".", 1)[0]
        keys.add(key)
    return keys


def cmd_client_keys(a):
    hits = client_message_keys(a.client or os.path.join(DEFAULT_CLIENT, "script",
                                                       "compiled.code"))
    data = {k: sorted(v) for k, v in sorted(hits.items())}
    if a.out:
        json.dump(data, open(a.out, "w", encoding="utf-8", newline="\n"), indent=1,
                  ensure_ascii=False)
        print("wrote %s (%d keys)" % (a.out, len(data)))
    else:
        for k in sorted(hits):
            print(k)
        print("total: %d keys" % len(hits))
    return 0


def cmd_check(a):
    snap = json.load(open(a.snapshot, encoding="utf-8"))
    client = a.client or DEFAULT_CLIENT
    keys = client_message_keys(os.path.join(client, "script", "compiled.code"))
    static = parse_messages_txt(os.path.join(client, "res", "common", "messages.txt"))
    language = parse_messages_txt(os.path.join(client, "res", "common",
                                               "messages.zh.txt"))
    db = set(snap["messages"])

    by_source = {"messages.txt": 0, "messages.zh.txt": 0, "eveMessages": 0, "none": 0}
    for k in keys:
        if k in static:
            by_source["messages.txt"] += 1
        elif k in language:
            by_source["messages.zh.txt"] += 1
        elif k in db:
            by_source["eveMessages"] += 1
        else:
            by_source["none"] += 1

    missing = sorted(k for k in keys if k not in static | language | db)
    print("client message keys: %d" % len(keys))
    print("covered by: %s" % ", ".join("%s=%d" % kv for kv in by_source.items()))
    print("db eveMessages keys never referenced by the client: %d"
          % sum(1 for k in db if k not in keys))
    if missing:
        print("keys the client asks for but no source defines (%d):" % len(missing))
        for k in missing[: a.limit]:
            print("  %-40s %s" % (k, ", ".join(sorted(keys[k])[:2])))
        if len(missing) > a.limit:
            print("  ... %d more" % (len(missing) - a.limit))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("manifest", help="hash the client install and db dumps")
    m.add_argument("--client", default=None)
    m.add_argument("--db", default=None)
    m.add_argument("--out", default=None)
    m.add_argument("--verify", default=None, help="check an existing manifest")
    m.set_defaults(func=cmd_manifest)

    s = sub.add_parser("snapshot", help="read-only facts and content markers from db/*.sql.gz")
    s.add_argument("--db", default=None)
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_snapshot)

    c = sub.add_parser("client-keys", help="message keys referenced by compiled.code")
    c.add_argument("--client", default=None)
    c.add_argument("--out", default=None)
    c.set_defaults(func=cmd_client_keys)

    k = sub.add_parser("check", help="cross-check client keys against text/db sources")
    k.add_argument("--snapshot", required=True)
    k.add_argument("--client", default=None)
    k.add_argument("--limit", type=int, default=40)
    k.set_defaults(func=cmd_check)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
