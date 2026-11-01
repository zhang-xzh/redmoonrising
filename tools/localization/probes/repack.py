import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eveccp

src, dst = sys.argv[1], sys.argv[2]
data = open(src, "rb").read()
items = [(p, v[0], v[1]) for (p, v) in eveccp.unpickle_container(data)]
open(dst, "wb").write(eveccp.pickle_container(items))
print("wrote", dst, os.path.getsize(dst), "from", len(items), "modules")
