# GHRSST MUR virtual stores

Draft group. `catalog.json` lists one STAC collection per dataset, each in
its own directory with the same forms as the other groups (`mdim.vrt`,
`kerchunk/`, `icechunk/`, `flat/`, `grist/`, `stac/`). The forms reference
the daily COGs in `ausantarctic/ghrsst-mur-v2`; no data is copied. The
kerchunk form needs imagecodecs in the reader (TIFF predictor). How they
are built and read: https://mdsumner.github.io/raad.virtualize/
