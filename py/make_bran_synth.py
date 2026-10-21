"""make_bran_synth.py -- tiny local netCDF4 files shaped like BRAN2023 daily
`temp`, to rehearse the many-chunks-per-file case without NCI access.

Like ocean_temp_YYYY_MM.nc: dims Time, st_ocean, yt_ocean, xt_ocean; int16,
shuffle + deflate, chunks 1 x 1 x 30 x 30 (BRAN: 300 x 300), scale_factor
0.007782219909131527, _FillValue -32768, axis units degrees_N / degrees_E
(valid CF, which wxy-virtual's lat/lon test missed). Months have different
lengths (3 and 4 days here), so the plan's destination offsets are not a
multiple of a constant. Chunks that are all land are never written, so
they have no bytes in the file: the store must record them as absent.

Usage: python make_bran_synth.py OUT_DIR
"""
import os
import sys

import netCDF4
import numpy as np

NZ, NY, NX, C = 4, 60, 90, 30
SCALE = 0.007782219909131527
FILL = -32768
MONTHS = [("2010_01", 3, 0.5), ("2010_02", 4, 3.5)]  # (tag, days, first day)


def main(out):
    os.makedirs(out, exist_ok=True)
    lat = -75 + 0.1 * np.arange(NY) + 0.05
    lon = 0.05 + 0.1 * np.arange(NX)
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    land = (la > -72.5) & (lo > 6.0)          # one corner block of chunks is land
    for tag, nt, t0 in MONTHS:
        ds = netCDF4.Dataset(os.path.join(out, f"ocean_temp_{tag}.nc"), "w", format="NETCDF4")
        for name, size in [("Time", None), ("st_ocean", NZ), ("yt_ocean", NY), ("xt_ocean", NX)]:
            ds.createDimension(name, size)
        t = ds.createVariable("Time", "f8", ("Time",))
        t.units, t.calendar = "days since 1979-01-01 00:00:00", "GREGORIAN"
        t[:] = 11323 + t0 + np.arange(nt)
        z = ds.createVariable("st_ocean", "f8", ("st_ocean",))
        z.units, z.positive = "meters", "down"
        z[:] = [2.5, 7.5, 12.5, 17.5]
        y = ds.createVariable("yt_ocean", "f8", ("yt_ocean",))
        y.units, y.long_name = "degrees_N", "tcell latitude"
        y[:] = lat
        x = ds.createVariable("xt_ocean", "f8", ("xt_ocean",))
        x.units, x.long_name = "degrees_E", "tcell longitude"
        x[:] = lon
        v = ds.createVariable("temp", "i2", ("Time", "st_ocean", "yt_ocean", "xt_ocean"),
                              zlib=True, complevel=1, shuffle=True, chunksizes=(1, 1, C, C),
                              fill_value=FILL)
        v.set_auto_maskandscale(False)
        v.long_name, v.units = "Potential temperature", "degrees C"
        v.scale_factor, v.add_offset = SCALE, 10.0
        for ti in range(nt):
            for zi in range(NZ):
                val = (8 * np.cos(np.radians(la * 3)) + 0.5 * np.sin(lo + ti) - zi) / SCALE
                val = np.where(land, FILL, np.round(val)).astype("i2")
                for yi in range(0, NY, C):
                    for xi in range(0, NX, C):
                        blk = val[yi:yi + C, xi:xi + C]
                        if np.all(blk == FILL):
                            continue  # never written: no bytes for this chunk
                        v[ti, zi, yi:yi + C, xi:xi + C] = blk
        ds.close()
    print(f"wrote {len(MONTHS)} files to {out}")


if __name__ == "__main__":
    main(sys.argv[1])
