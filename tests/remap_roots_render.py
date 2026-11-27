"""render_icechunk.remap_roots names a root by its rules' `root`, else by the
slug of the prefix (byterefs decision 0014), and refuses a bad name or two
prefixes that give one name. Run from the repository root:
  python tests/remap_roots_render.py
"""
import sys

sys.path.insert(0, "py")
from render_icechunk import remap_roots, root_name  # noqa: E402

doc = {"remap": [
    {"target": "public", "prefix": "/vsicurl/https://", "replacement": "https://"},
    {"target": "public", "prefix": "/g/data/gb6/", "replacement": "https://thredds.nci.org.au/thredds/fileServer/gb6/", "root": "bran2023"},
    {"target": "gdal", "prefix": "/g/data/gb6/", "replacement": "/vsicurl/https://thredds.nci.org.au/thredds/fileServer/gb6/", "root": "bran2023"},
]}
roots, table = remap_roots(doc, "public")
assert roots["bran2023"] == ("/g/data/gb6/", "https://thredds.nci.org.au/thredds/fileServer/gb6/"), roots
assert roots["vsicurl"] == ("/vsicurl/https://", "https://"), roots
assert set(table["bran2023"]["targets"]) == {"public", "gdal"}, table

for prefix, name in [("/g/data/gb6/", "g-data-gb6"), ("/vsicurl/https://", "vsicurl"),
                     ("https://noaadata.apps.nsidc.org/NOAA/G02202_V6/", "noaadata-apps-nsidc-org-NOAA-G02202-V6"),
                     ("/vsicurl/https://data.source.coop/ausantarctic/", "vsicurl-data-source-coop-ausantarctic")]:
    assert root_name(prefix) == name, (prefix, root_name(prefix))


def exits(d):
    try:
        remap_roots(d, "public")
    except SystemExit:
        return True
    return False


assert exits({"remap": [{"target": "public", "prefix": "/a/", "replacement": "https://h/a/", "root": "bad name"}]})
assert exits({"remap": [{"target": "public", "prefix": "/g/data/gb6/", "replacement": "https://h/1/"},
                        {"target": "public", "prefix": "/g-data/gb6/", "replacement": "https://h/2/"}]})
print("PASS tests/remap_roots_render.py")
