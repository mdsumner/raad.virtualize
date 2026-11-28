"""thumbnail.write_render: the `renders` object from the thumbnail stretch.
`rescale` is in stored units, so a CF-packed array's physical stretch is
converted back with its scale_factor and add_offset; nothing is written for
a palette other than viridis, a log10 stretch, no assets or an empty stretch.
Run from the repository root:
  python tests/thumbnail_render.py
"""
import json
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, "py")
from thumbnail import write_render  # noqa: E402

path = os.path.join(tempfile.mkdtemp(), "render.json")


def written(**kw):
    args = dict(path=path, array="temp", stretch=(-1.798, 30.2), scale=0.007782219909131527,
                offset=245.0, palette="viridis", log10=False, assets=["icechunk"], what="temp [0,0]")
    args.update(kw)
    write_render(**args)
    return json.load(open(path)) if os.path.exists(path) else None


# packed int16 (BRAN temp): the stretch in degrees, rescale in stored units
r = written()["temp"]
lo, hi = r["rescale"][0]
assert abs(lo * 0.007782219909131527 + 245 - -1.798) < 1e-3 and abs(hi * 0.007782219909131527 + 245 - 30.2) < 1e-3, r
assert -31720 < lo < -31700 and -27610 < hi < -27590, r
assert r["assets"] == ["icechunk"] and r["colormap_name"] == "viridis", r

# unpacked float: rescale is the stretch itself
r = written(array="eta_t", stretch=(-1.816, 0.8266), scale=None, offset=None,
            assets=["icechunk", "browser"])["eta_t"]
assert r["rescale"] == [[-1.816, 0.8266]] and r["assets"] == ["icechunk", "browser"], r

# a negative scale keeps the range ordered
assert written(scale=-2.0, offset=0.0)["temp"]["rescale"] == [[-15.1, 0.899]]

# nothing written, and a stale file removed
for kw in (dict(palette="topo"), dict(log10=True), dict(assets=[]),
           dict(stretch=(np.nan, np.nan)), dict(stretch=(1.0, 1.0))):
    written()
    assert written(**kw) is None, kw
print("thumbnail_render: ok")
