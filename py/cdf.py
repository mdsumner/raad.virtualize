"""cdf.py -- header of a classic netCDF file (CDF-1, CDF-2, CDF-5), and the
byte range of every variable.

Classic netCDF stores each variable uncompressed, in big-endian order, in
one contiguous range (a non-record variable) or in one slab per record,
interleaved with the other record variables at a stride of the record size.
So the bytes of any run of whole leading-axis rows are known from the header
alone: row i of a non-record variable starts at begin + i * rowbytes, record
r of a record variable at begin + r * recsize. GDAL's netCDF driver has no
GetRawBlockInfo for classic files, so harvest.py reads them here (engine
cdf).

The header is read through GDAL's virtual file system (any path GDAL
opens: local, /vsicurl/, /vsis3/), from the first 64 KB and more as
needed. Format: NetCDF Users Guide, "File Format Specifications"
(https://docs.unidata.ucar.edu/netcdf-c/current/file_format_specifications.html).

  python cdf.py FILE      print the header as JSON
"""
import json
import struct
import sys

from osgeo import gdal

gdal.UseExceptions()

NC_DIMENSION, NC_VARIABLE, NC_ATTRIBUTE = 0x0A, 0x0B, 0x0C
# nc_type -> numpy dtype (big-endian); 7..11 are CDF-5 only
DTYPE = {1: "|i1", 2: "|S1", 3: ">i2", 4: ">i4", 5: ">f4", 6: ">f8",
         7: "|u1", 8: ">u2", 9: ">u4", 10: ">i8", 11: ">u8"}
STRUCT = {1: "b", 3: "h", 4: "i", 5: "f", 6: "d", 7: "B", 8: "H", 9: "I", 10: "q", 11: "Q"}
SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 4, 6: 8, 7: 1, 8: 2, 9: 4, 10: 8, 11: 8}
STREAMING = 0xFFFFFFFF


class NotClassic(Exception):
    pass


class _Reader:
    """Header bytes of `path`, fetched in growing blocks through VSI."""

    def __init__(self, path, first=65536):
        self.f = gdal.VSIFOpenL(path, "rb")
        if self.f is None:
            raise OSError(f"cannot open {path}")
        self.buf = b""
        self.pos = 0
        self._more(first)

    def _more(self, n):
        gdal.VSIFSeekL(self.f, len(self.buf), 0)
        got = gdal.VSIFReadL(1, n, self.f) or b""
        if not got:
            raise OSError("short read: the header runs past the end of the file, or the read failed")
        self.buf += got

    def take(self, n):
        while self.pos + n > len(self.buf):
            self._more(max(65536, len(self.buf)))
        out = self.buf[self.pos:self.pos + n]
        self.pos += n
        return out

    def close(self):
        gdal.VSIFCloseL(self.f)


def _pad4(n):
    return (n + 3) & ~3


def read_header(path):
    """{version, numrecs, dims: [(name, size)], attrs: {..}, vars: {name:
    {dims, shape, dtype, nc_type, vsize, begin, record, attrs}}, recsize,
    header_bytes}. A record dimension has size 0 in `dims`; a record
    variable's shape carries numrecs on that axis."""
    r = _Reader(path)
    try:
        magic = r.take(4)
        if magic[:3] != b"CDF" or magic[3] not in (1, 2, 5):
            raise NotClassic(f"{path}: not a classic netCDF file (magic {magic!r})")
        ver = magic[3]
        nonneg = ">Q" if ver == 5 else ">I"
        nbytes = 8 if ver == 5 else 4
        offset = ">Q" if ver in (2, 5) else ">I"

        def num():
            return struct.unpack(nonneg, r.take(nbytes))[0]

        def name():
            n = num()
            return r.take(_pad4(n))[:n].decode("utf-8")

        def values(t, n):
            raw = r.take(_pad4(n * SIZE[t]))[:n * SIZE[t]]
            if t == 2:
                return raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
            v = list(struct.unpack(f">{n}{STRUCT[t]}", raw))
            return v[0] if n == 1 else v

        def att_list():
            tag, n = struct.unpack(">I", r.take(4))[0], num()
            if tag == 0 and n == 0:
                return {}
            if tag != NC_ATTRIBUTE:
                raise ValueError(f"{path}: expected an attribute list, tag {tag:#x}")
            out = {}
            for _ in range(n):
                k = name()
                t = struct.unpack(">I", r.take(4))[0]
                out[k] = values(t, num())
            return out

        numrecs = num()
        tag, n = struct.unpack(">I", r.take(4))[0], num()
        dims = []
        if not (tag == 0 and n == 0):
            if tag != NC_DIMENSION:
                raise ValueError(f"{path}: expected a dimension list, tag {tag:#x}")
            dims = [(name(), num()) for _ in range(n)]
        gattrs = att_list()
        tag, n = struct.unpack(">I", r.take(4))[0], num()
        variables = {}
        if not (tag == 0 and n == 0):
            if tag != NC_VARIABLE:
                raise ValueError(f"{path}: expected a variable list, tag {tag:#x}")
            for _ in range(n):
                vn = name()
                ids = [struct.unpack(nonneg, r.take(nbytes))[0] for _ in range(num())]
                va = att_list()
                t = struct.unpack(">I", r.take(4))[0]
                vsize = num()
                begin = struct.unpack(offset, r.take(8 if ver in (2, 5) else 4))[0]
                record = bool(ids) and dims[ids[0]][1] == 0
                shape = [numrecs if (k == 0 and record) else dims[d][1] for k, d in enumerate(ids)]
                variables[vn] = {"dims": [dims[d][0] for d in ids], "shape": shape,
                                 "dtype": DTYPE[t], "nc_type": t, "vsize": vsize,
                                 "begin": begin, "record": record, "attrs": va}
        hdr = r.pos
    finally:
        r.close()
    rec = [v for v in variables.values() if v["record"]]
    # one record variable: its records are not padded to 4 bytes
    for v in rec:
        v["recbytes"] = _prod(v["shape"][1:]) * SIZE[v["nc_type"]]
    recsize = rec[0]["recbytes"] if len(rec) == 1 else sum(v["vsize"] for v in rec)
    return {"version": ver, "numrecs": numrecs, "dims": dims, "attrs": gattrs,
            "vars": variables, "recsize": recsize, "header_bytes": hdr}


def _prod(x):
    p = 1
    for v in x:
        p *= v
    return p


def rows(var, recsize, lead=1):
    """(offset, size) of each run of `lead` leading-axis rows of a variable
    (records, for a record variable). The leading axis must be a multiple of
    `lead`, so every run is whole; a rank-0 variable is one run."""
    shape = var["shape"]
    if not shape:
        return [(var["begin"], SIZE[var["nc_type"]])]
    if var["record"]:
        if lead != 1:
            raise ValueError("a record variable is read one record a chunk")
        n = var["recbytes"]
        return [(var["begin"] + i * recsize, n) for i in range(shape[0])]
    if shape[0] % lead:
        raise ValueError(f"leading axis {shape[0]} is not a multiple of {lead}")
    rb = _prod(shape[1:]) * SIZE[var["nc_type"]]
    return [(var["begin"] + i * lead * rb, lead * rb) for i in range(shape[0] // lead)]


def read_var(path, var, recsize=0):
    """The values of a non-record variable, or of a record variable, as a
    numpy array (one range read, or one a record)."""
    import numpy as np
    f = gdal.VSIFOpenL(path, "rb")
    try:
        parts = []
        for off, n in rows(var, recsize, 1) if var["record"] else [(var["begin"], _prod(var["shape"]) * SIZE[var["nc_type"]])]:
            gdal.VSIFSeekL(f, off, 0)
            parts.append(gdal.VSIFReadL(1, n, f))
    finally:
        gdal.VSIFCloseL(f)
    return np.frombuffer(b"".join(parts), dtype=var["dtype"]).reshape(var["shape"])


if __name__ == "__main__":
    h = read_header(sys.argv[1])
    json.dump(h, sys.stdout, indent=1, default=str)
    print()
