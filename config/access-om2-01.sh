# ACCESS-OM2-01 (COSIMA, 0.1 degree MOM5-CICE5, JRA55-do v1.4.0) interannual
# forcing run, cycle 4 (01deg_jra55v140_iaf_cycle4, 1958-2018, the cycle with
# WOMBAT BGC), raw payu output on NCI /g/data/cj50, published over NCI
# THREDDS (fileServer). output732/ .. output991/ hold three months each. MOM
# writes one variable per file per month:
# output<NNN>/ocean/<stem>-ym_<YYYY>_<MM>.nc, e.g.
# ocean-2d-surface_pot_temp-1-daily-mean-ym_1958_01.nc (float32,
# time x 2700 x 3600, chunks 1 x 540 x 720, shuffle + deflate 5, fill -1e20).
# One dataset per file stem; the plan is `gdal mdim mosaic` along time.
#
# Built in situ on Gadi from the /g/data listing of the standing job
# (py/gdata_listing.py, source gdata_cj50_om2_01_iaf_cycle4; hpc/nci/standing.tsv):
#
#   GDATA_LISTINGS=DIR       listing directory (required)
#   OM201_STEM               file stem, default
#                            ocean-2d-surface_pot_temp-1-daily-mean
#   OM201_VAR                the array in the file, default the variable
#                            part of the stem (surface_pot_temp)
#   OM201_FIRST, OM201_LAST  inclusive months, YYYY_MM (default all); a subset
#                            gets its own DATASET name
#   OM201_GRID=1 (default)   add the 2D cell centres geolon_t and geolat_t from
#                            output732/ocean/ocean-2d-geol*_t.nc (py/plan_join.py);
#                            the grid is tripolar, so xt_ocean/yt_ocean are
#                            nominal north of about 65N. 0 leaves them out
#
# The 2019-2023 extension (01deg_jra55v140_iaf_cycle4_jra55v150_extension)
# is in /g/data/ik11, which NCI does not publish, so it is not indexed.
# Licence: /g/data/cj50/access-om2/license.txt, CC BY-NC-ND 4.0.
OM201_ROOT=/g/data/cj50/access-om2/raw-output/access-om2-01/01deg_jra55v140_iaf_cycle4
OM201_SOURCE=gdata_cj50_om2_01_iaf_cycle4
OM201_STEM=${OM201_STEM:-ocean-2d-surface_pot_temp-1-daily-mean}
OM201_VAR=${OM201_VAR:-$(echo "$OM201_STEM" | sed -E 's/^ocean(bgc)?-[23]d-(.*)-1-(daily|monthly)-.*$/\2/')}
OM201_GRID=${OM201_GRID:-1}
ARRAYS=$OM201_VAR
[ "$OM201_GRID" = 1 ] && ARRAYS="$ARRAYS geolon_t geolat_t"
DATASET=access-om2-01.iaf-cycle4.$OM201_STEM${OM201_FIRST:+-$OM201_FIRST}${OM201_LAST:+-$OM201_LAST}
# product group (products/cosima/): the scratch prefix on source.coop
PRODUCT_GROUP=cosima
sources() {
  : "${GDATA_LISTINGS:?set GDATA_LISTINGS (the /g/data listing directory, py/gdata_listing.py)}"
  "$PYTHON" "$HERE/py/corpus.py" --corpus "$GDATA_LISTINGS" --source "$OM201_SOURCE" \
    --meta "$WORK/sources.meta.tsv" \
    --match "^$OM201_ROOT/output[0-9]+/ocean/$OM201_STEM-ym_[0-9]{4}_[0-9]{2}\.nc\$" \
    --date="-ym_([0-9]{4}_[0-9]{2})\.nc\$" \
    ${OM201_FIRST:+--first "$OM201_FIRST"} ${OM201_LAST:+--last "$OM201_LAST"}
  if [ "$OM201_GRID" = 1 ]; then
    "$PYTHON" "$HERE/py/corpus.py" --corpus "$GDATA_LISTINGS" --source "$OM201_SOURCE" \
      --meta "$WORK/sources.meta.fx.tsv" \
      --match "^$OM201_ROOT/output732/ocean/ocean-2d-geol(on|at)_t\.nc\$" \
      --date='^ocean-2d-(geolon_t|geolat_t)\.nc$'
    tail -n +2 "$WORK/sources.meta.fx.tsv" >> "$WORK/sources.meta.tsv"
    rm -f "$WORK/sources.meta.fx.tsv"
  fi
}
# the monthly files mosaicked along time, then the grid arrays joined
make_plan() {
  grep -Ev -- '/ocean-2d-geol(on|at)_t\.nc$' "$WORK/sources.txt" > "$WORK/sources.months.txt"
  "$GDAL" mdim mosaic --overwrite --array "$OM201_VAR" "@$WORK/sources.months.txt" "$WORK/plan.vrt"
  if [ "$OM201_GRID" = 1 ]; then
    local j=() f
    while read -r f; do
      case $f in */ocean-2d-geolon_t.nc) j+=(--source "$f:geolon_t") ;; */ocean-2d-geolat_t.nc) j+=(--source "$f:geolat_t") ;; esac
    done < <(grep -E -- '/ocean-2d-geol(on|at)_t\.nc$' "$WORK/sources.txt")
    [ ${#j[@]} -eq 4 ] || { echo "make_plan: expected ocean-2d-geolon_t.nc and ocean-2d-geolat_t.nc in sources.txt" >&2; return 1; }
    "$PYTHON" "$HERE/py/plan_join.py" --plan "$WORK/plan.vrt" --gdal "$GDAL" "${j[@]}"
  fi
}
# target|prefix|replacement, applied at render (sources stay /g/data paths)
REMAPS=("public|/g/data/cj50/|https://thredds.nci.org.au/thredds/fileServer/cj50/"
        "gdal|/g/data/cj50/|/vsicurl/https://thredds.nci.org.au/thredds/fileServer/cj50/")
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=gdal
export STAC_LICENSE=${STAC_LICENSE:-CC-BY-NC-ND-4.0}
export STAC_TITLE=${STAC_TITLE:-ACCESS-OM2-01 IAF cycle 4 $OM201_STEM (COSIMA, 0.1 degree, 1958-2018)}
# grist rows need a time axis: list the variable, not the 2D grid arrays
export GRIST_ARRAYS=${GRIST_ARRAYS:-$OM201_VAR}
WORKERS=${WORKERS:-8}
