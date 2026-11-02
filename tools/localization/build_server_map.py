"""Build config/localization/server_<lang>.json: server table text -> Chinese.

The server keeps its bulk data in English (the retail 3913 database) and applies
this overlay when it builds a per-language bulk for a session.  Keys are
"table" -> "column" -> primary key -> translated text, so a missing entry simply
falls back to the English row.

Inputs:
  --en    messageID -> English, dumped from the retail 3396210 client
          (tools/FsdDump/dump_localization.py --lang en-us)
  --zh    messageID -> Chinese, same client
          (EveJS: config/client_localization_fsd_zh.json)
  --db    the official 3913 table dumps (db/*.sql.gz); they are only read

Matching is by the exact English text of the 3913 row.  A row that was renamed
or rewritten since 2006 therefore keeps its English text: the overlay never
invents a translation for text it did not see.
"""
import argparse
import collections
import gzip
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

EN_JSON = os.environ.get("RMR_LOC_EN") or os.path.join(
    os.environ.get("TEMP", "."), "opencode", "loc_en.json")
ZH_JSON = r"M:\EVE-LOCAL\EveJS\config\client_localization_fsd_zh.json"
DB_DIR = os.path.join(ROOT, "db")
OUT = os.path.join(ROOT, "config", "localization", "server_zh.json")

# table -> (primary key column, display columns).  Only tables the server sends
# as bulk data are listed; player-generated names are never translated.
TABLES = {
    "invTypes": ("typeID", ["typeName", "description"]),
    "invGroups": ("groupID", ["groupName", "description"]),
    "invCategories": ("categoryID", ["categoryName", "description"]),
    "invMetaGroups": ("metaGroupID", ["metaGroupName", "description"]),
    "dgmAttributeTypes": ("attributeID", ["attributeName", "displayName", "description"]),
    "dgmEffects": ("effectID", ["effectName", "displayName", "description"]),
    "billTypes": ("billTypeID", ["billTypeName", "description"]),
    "ramAssemblyLineTypes": ("assemblyLineTypeID", ["assemblyLineTypeName", "description"]),
    "ramActivities": ("activityID", ["activityName", "description"]),
    "ramCompletedStatuses": ("completedStatusID", ["completedStatusName", "completedStatusText"]),
    "eveRoles": ("roleID", ["roleName", "description"]),
    "eveFlags": ("flagID", ["flagName", "flagText"]),
    "chrRaces": ("raceID", ["raceName", "description"]),
    "chrBloodlines": (
        "bloodlineID",
        ["bloodlineName", "description", "maleDescription", "femaleDescription"],
    ),
    "eveStatistics": ("statisticID", ["statisticName", "description"]),
    "eveUnits": ("unitID", ["unitName", "displayName", "description"]),
    "channelTypes": ("channelTypeID", ["channelTypeName", "defaultName"]),
    "eveStaticLocations": ("locationID", ["locationName"]),
}

# Short English names collide in the message dump (several messageIDs share the
# same text, e.g. a ship and a skill).  The most frequent translation wins.
MAX_WORDS = 40


def norm(s):
    s = s.replace("\x85", "...").replace("\u2026", "...")
    s = s.replace("\x91", "'").replace("\x92", "'")
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def build_map(en, zh):
    counts = collections.defaultdict(collections.Counter)
    dupes = 0
    for mid, text in en.items():
        z = zh.get(mid)
        if not (isinstance(text, str) and isinstance(z, str) and z.strip() and text.strip()):
            continue
        t = norm(text)
        if not t or len(t.split()) > MAX_WORDS:
            continue
        counts[t][z] += 1
        if len(counts[t]) > 1:
            dupes += 1
    # One English string can be several messageIDs with different Chinese
    # (a word used in different UI contexts); the most frequent one wins.
    exact = {t: c.most_common(1)[0][0] for t, c in counts.items()}
    fuzzy = collections.defaultdict(collections.Counter)
    for t, c in counts.items():
        for z, n in c.items():
            fuzzy[t.lower()][z] += n
    return exact, fuzzy, dupes


def unescape(field):
    """Undo pg_dump COPY text escaping."""
    if field == r"\N":
        return None
    out = []
    i = 0
    while i < len(field):
        c = field[i]
        if c == "\\" and i + 1 < len(field):
            n = field[i + 1]
            out.append(
                {"t": "\t", "n": "\n", "r": "\r", "b": "\b", "f": "\f",
                 "v": "\v", "\\": "\\"}.get(n, n)
            )
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def read_copy(path, wanted):
    """Yield dict rows from the COPY block of a pg_dump file."""
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        cols = None
        for line in f:
            if line.startswith("COPY "):
                m = re.search(r"\((.*)\) FROM stdin;", line)
                if not m:
                    cols = None
                    continue
                names = [c.strip().strip('"') for c in m.group(1).split(",")]
                if all(c in names for c in wanted):
                    cols = names
                else:
                    cols = None
                continue
            if cols is None:
                continue
            if line.rstrip("\n") == r"\.":
                cols = None
                continue
            values = [unescape(v) for v in line.rstrip("\n").split("\t")]
            if len(values) != len(cols):
                continue
            yield dict(zip(cols, values))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--en", default=EN_JSON, help="messageID -> English (3396210 dump)")
    ap.add_argument("--zh", default=ZH_JSON, help="messageID -> Chinese")
    ap.add_argument("--db", default=DB_DIR, help="directory of the official db/*.sql.gz")
    ap.add_argument("--out", default=OUT, help="output json")
    ap.add_argument("--lang", default="zh", help="output language tag")
    a = ap.parse_args()

    en = json.load(open(a.en, encoding="utf-8"))
    zh = json.load(open(a.zh, encoding="utf-8"))
    exact, fuzzy, dupes = build_map(en, zh)

    out = {}
    total = {"rows": 0, "texts": 0, "translated": 0, "fuzzy": 0, "skipped": 0}
    for table, (key, columns) in TABLES.items():
        path = os.path.join(a.db, table + ".sql.gz")
        if not os.path.exists(path):
            print(f"{table}: no dump; skipped")
            continue
        wanted = [key] + columns
        rows = 0
        texts = 0
        translated = 0
        table_out = {}
        for row in read_copy(path, wanted):
            key_value = row.get(key)
            if not key_value:
                continue
            rows += 1
            per_row = {}
            for column in columns:
                text = row.get(column)
                if not text:
                    continue
                texts += 1
                t = norm(text)
                z = exact.get(t)
                if z is None:
                    c = fuzzy.get(t.lower())
                    # Only a case/spacing variant with one known translation is
                    # safe; several candidates mean the English word is
                    # ambiguous (a ship and a skill, say), so keep English.
                    if c and len(c) == 1:
                        z = next(iter(c))
                        total["fuzzy"] += 1
                    elif c:
                        total["skipped"] += 1
                if z is None or not z.strip() or z == text:
                    continue
                per_row[column] = z
                translated += 1
            if per_row:
                table_out[key_value] = per_row
        if table_out:
            # Pivot from key -> {column: text} to column -> key -> text.
            pivot = {}
            for key_value, per_row in table_out.items():
                for column, z in per_row.items():
                    pivot.setdefault(column, {})[key_value] = z
            out[table] = pivot
        print(
            f"{table}: {rows} rows, {texts} texts, {translated} translated "
            f"({100.0 * translated / texts if texts else 0:.1f}%)"
        )
        total["rows"] += rows
        total["texts"] += texts
        total["translated"] += translated

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=0, sort_keys=True)
        f.write("\n")
    size = os.path.getsize(a.out)
    print(
        f"total: {total['translated']}/{total['texts']} texts from {total['rows']} rows, "
        f"{total['fuzzy']} case-only matches, {total['skipped']} ambiguous strings kept English, "
        f"{dupes} duplicate English keys, {size / 1e6:.2f} MB"
    )
    print("->", a.out)


if __name__ == "__main__":
    main()
