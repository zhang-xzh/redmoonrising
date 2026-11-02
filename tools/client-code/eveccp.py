#!/usr/bin/env python3
"""Read/write the EVE 'compiled.code' container (Python 2.4 pickle + marshal).

The container is a Python-2 protocol-1 pickle:
    [ (module_path:str, (marshalled_code:str, aux:int)), ... ]

Each marshalled blob is a Python 2.4 code object using the 2.4 marshal dialect
(4-byte code header fields, interned strings 't' / string refs 'R').

This module re-implements enough of marshal to round-trip unchanged data
byte-for-byte and to rewrite string constants.
"""
import struct
import sys

# ---------------------------------------------------------------- marshal read

class Code:
    __slots__ = ("argcount", "nlocals", "stacksize", "flags", "code",
                 "consts", "names", "varnames", "freevars", "cellvars",
                 "filename", "name", "firstlineno", "lnotab")

    def __init__(self):
        self.argcount = self.nlocals = self.stacksize = self.flags = 0
        self.code = b""
        self.consts = ()
        self.names = ()
        self.varnames = ()
        self.freevars = ()
        self.cellvars = ()
        self.filename = b""
        self.name = b""
        self.firstlineno = 0
        self.lnotab = b""

    def __repr__(self):
        return "<code %s>" % (self.name,)


class BStr(bytes):
    """A Python-2 byte string; `interned` remembers the original tag."""
    interned = False
    def __new__(cls, value, interned=False):
        o = bytes.__new__(cls, value)
        o.interned = interned
        return o


class UStr(str):
    pass


class PyInt(int):
    pass


class PyLong:
    __slots__ = ("negative", "digits")
    def __init__(self, negative, digits):
        self.negative = negative
        self.digits = digits


class PyFloat:
    __slots__ = ("text",)
    def __init__(self, text):
        self.text = text


class PyComplex:
    __slots__ = ("real", "imag")
    def __init__(self, real, imag):
        self.real = real
        self.imag = imag


class _Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0
        self.refs = []

    def byte(self):
        b = self.d[self.p]
        self.p += 1
        return b

    def bytes(self, n):
        s = self.d[self.p:self.p + n]
        self.p += n
        return s

    def long(self):
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def obj(self):
        t = chr(self.byte())
        if t == "0":
            return None
        if t == "N":
            return None
        if t == "F":
            return False
        if t == "T":
            return True
        if t == "S":
            return StopIteration
        if t == ".":
            return Ellipsis
        if t == "i":
            return PyInt(self.long())
        if t == "I":
            lo = struct.unpack_from("<I", self.d, self.p)[0]
            hi = struct.unpack_from("<I", self.d, self.p + 4)[0]
            self.p += 8
            return PyInt(lo | (hi << 32))
        if t == "l":
            n = self.long()
            neg = n < 0
            n = abs(n)
            digits = [struct.unpack_from("<H", self.d, self.p + 2 * i)[0] for i in range(n)]
            self.p += 2 * n
            return PyLong(neg, digits)
        if t == "f":
            n = self.byte()
            return PyFloat(self.bytes(n).decode("ascii"))
        if t == "x":
            n = self.byte(); re_ = self.bytes(n).decode("ascii")
            n = self.byte(); im = self.bytes(n).decode("ascii")
            return PyComplex(re_, im)
        if t in ("s", "t"):
            n = self.long()
            v = BStr(self.bytes(n), interned=(t == "t"))
            self.refs.append(v)
            return v
        if t == "u":
            n = self.long()
            return UStr(self.bytes(n).decode("utf-8"))
        if t == "R":
            return self.refs[self.long()]
        if t == "(":
            n = self.long()
            return tuple(self.obj() for _ in range(n))
        if t == "[":
            n = self.long()
            return [self.obj() for _ in range(n)]
        if t == "{":
            d = {}
            while True:
                k = self.obj()
                if k is None:
                    break
                d[k] = self.obj()
            return d
        if t == "c":
            co = Code()
            co.argcount = self.long()
            co.nlocals = self.long()
            co.stacksize = self.long()
            co.flags = self.long()
            co.code = self.obj()
            co.consts = self.obj()
            co.names = self.obj()
            co.varnames = self.obj()
            co.freevars = self.obj()
            co.cellvars = self.obj()
            co.filename = self.obj()
            co.name = self.obj()
            co.firstlineno = self.long()
            co.lnotab = self.obj()
            return co
        raise ValueError("marshal: unknown type %r at %d" % (t, self.p - 1))


def loads(data):
    return _Reader(data).obj()


# --------------------------------------------------------------- marshal write

class _Writer:
    def __init__(self):
        self.out = bytearray()
        self.strings = {}
        self.refs = 0

    def byte(self, b):
        self.out.append(b & 0xFF)

    def bytes(self, s):
        self.out += s

    def long(self, v):
        self.out += struct.pack("<i", v)

    def str_obj(self, v):
        if v.interned:
            idx = self.strings.get(bytes(v))
            if idx is not None:
                self.byte(ord("R"))
                self.long(idx)
                return
            self.strings[bytes(v)] = self.refs
            self.refs += 1
            self.byte(ord("t"))
        else:
            self.byte(ord("s"))
        self.long(len(v))
        self.bytes(bytes(v))

    def obj(self, v):
        if v is None:
            self.byte(ord("N"))
        elif v is True:
            self.byte(ord("T"))
        elif v is False:
            self.byte(ord("F"))
        elif v is StopIteration:
            self.byte(ord("S"))
        elif v is Ellipsis:
            self.byte(ord("."))
        elif isinstance(v, PyInt):
            if -(2 ** 31) <= v < 2 ** 31:
                self.byte(ord("i")); self.long(int(v))
            else:
                self.byte(ord("I"))
                self.bytes(struct.pack("<II", int(v) & 0xFFFFFFFF, (int(v) >> 32) & 0xFFFFFFFF))
        elif isinstance(v, PyLong):
            self.byte(ord("l"))
            self.long(-len(v.digits) if v.negative else len(v.digits))
            for d in v.digits:
                self.bytes(struct.pack("<H", d))
        elif isinstance(v, PyFloat):
            self.byte(ord("f")); self.byte(len(v.text)); self.bytes(v.text.encode("ascii"))
        elif isinstance(v, PyComplex):
            self.byte(ord("x"))
            self.byte(len(v.real)); self.bytes(v.real.encode("ascii"))
            self.byte(len(v.imag)); self.bytes(v.imag.encode("ascii"))
        elif isinstance(v, BStr):
            self.str_obj(v)
        elif isinstance(v, UStr):
            b = v.encode("utf-8")
            self.byte(ord("u")); self.long(len(b)); self.bytes(b)
        elif isinstance(v, tuple):
            self.byte(ord("(")); self.long(len(v))
            for x in v:
                self.obj(x)
        elif isinstance(v, list):
            self.byte(ord("[")); self.long(len(v))
            for x in v:
                self.obj(x)
        elif isinstance(v, dict):
            self.byte(ord("{"))
            for k, val in v.items():
                self.obj(k); self.obj(val)
            self.byte(ord("0"))
        elif isinstance(v, Code):
            self.byte(ord("c"))
            self.long(v.argcount); self.long(v.nlocals)
            self.long(v.stacksize); self.long(v.flags)
            for f in ("code", "consts", "names", "varnames", "freevars",
                      "cellvars", "filename", "name"):
                self.obj(getattr(v, f))
            self.long(v.firstlineno)
            self.obj(v.lnotab)
        else:
            raise ValueError("marshal: cannot write %r" % (type(v),))


def dumps(v):
    w = _Writer()
    w.obj(v)
    return bytes(w.out)


# ------------------------------------------------------------ pickle container

def unpickle_container(data):
    """Parse the protocol-1 pickle of [(path, (marshal, aux)), ...]."""
    import pickle, io
    return pickle.Unpickler(io.BytesIO(data), encoding="bytes").load()


def _skip_memo(data, pos):
    op = data[pos:pos + 1]
    if op == b"q":      # BINPUT
        return pos + 2
    if op == b"r":      # LONG_BINPUT
        return pos + 5
    if op == b"p":      # PUT
        end = data.index(b"\n", pos)
        return end + 1
    return pos


def _pickle_str(data, pos):
    op = data[pos:pos + 1]; pos += 1
    if op == b"U":
        n = data[pos]; pos += 1
        return data[pos:pos + n], pos + n
    if op == b"T":
        n = struct.unpack_from("<I", data, pos)[0]; pos += 4
        return data[pos:pos + n], pos + n
    if op == b"V":
        end = data.index(b"\n", pos)
        return data[pos:end], end + 1
    raise ValueError("pickle string op %r" % op)


def _pickle_int(data, pos):
    op = data[pos:pos + 1]; pos += 1
    if op == b"J":
        v = struct.unpack_from("<i", data, pos)[0]; pos += 4
        return v, pos
    if op == b"K":
        return data[pos], pos + 1
    if op == b"M":
        return struct.unpack_from("<H", data, pos)[0], pos + 2
    if op == b"I":
        return struct.unpack_from("<i", data, pos)[0], pos + 4  # 2.3+? not used here
    raise ValueError("pickle int op %r" % op)


def _pickle_item(data, pos):
    op = data[pos:pos + 1]
    if op == b"(":
        pos += 1
        vals = []
        while data[pos:pos + 1] != b"t":
            if data[pos:pos + 1] in (b"U", b"T", b"V"):
                v, pos = _pickle_str(data, pos)
            elif data[pos:pos + 1] in (b"J", b"K", b"M"):
                v, pos = _pickle_int(data, pos)
            elif data[pos:pos + 1] == b"(":
                v, pos = _pickle_item(data, pos)
            else:
                raise ValueError("pickle item op %r" % data[pos:pos + 1])
            vals.append(v)
            pos = _skip_memo(data, pos)
        pos += 1  # 't'
        return tuple(vals), pos
    if op in (b"U", b"T", b"V"):
        return _pickle_str(data, pos)
    if op in (b"J", b"K", b"M"):
        return _pickle_int(data, pos)
    raise ValueError("pickle item op %r" % op)


def pickle_container(items):
    out = bytearray(b"](")
    for path, blob, aux in items:
        out += b"("
        p = path.encode("utf-8") if isinstance(path, str) else path
        out += _p_str(p)
        out += b"(" + _p_str(blob) + b"J" + struct.pack("<i", aux) + b"t"
        out += b"t"
    out += b"e."
    return bytes(out)


def _p_str(s):
    if len(s) < 256:
        return b"U" + bytes([len(s)]) + s
    return b"T" + struct.pack("<I", len(s)) + s
