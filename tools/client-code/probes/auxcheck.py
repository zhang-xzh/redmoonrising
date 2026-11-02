import sys, os, zlib, binascii
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import eveccp

src = sys.argv[1] if len(sys.argv) > 1 else r"M:\EVE-LOCAL\inputs\EVE-Online-3913\script\compiled.code"
data = open(src, "rb").read()
items = [(p, v[0], v[1]) for (p, v) in eveccp.unpickle_container(data)]
print("n", len(items))
for i in (0, 1, 2, 10, 100):
    path, blob, aux = items[i]
    root = eveccp.loads(blob)
    print(i, "aux", aux, "len", len(blob),
          "crc32", zlib.crc32(blob), "adler", zlib.adler32(blob),
          "code", len(root.code), "consts", len(root.consts),
          "crc32&0x7fff", zlib.crc32(blob) & 0x7fff,
          "adler&0x7fff", zlib.adler32(blob) & 0x7fff)
    print("   path", path[:70])
# check relation over all
import collections
rel = collections.Counter()
for path, blob, aux in items:
    root = eveccp.loads(blob)
    if aux == len(blob): rel["len"] += 1
    if aux == (zlib.crc32(blob) & 0xFFFF): rel["crc16"] += 1
    if aux == (zlib.adler32(blob) & 0xFFFF): rel["adler16"] += 1
    if aux == len(root.code): rel["code"] += 1
    if aux == len(root.consts): rel["consts"] += 1
print(rel)
