# ACCESS-ESM1.6 historical run (ACCESS-NRI), native payu output on the
# Pawsey Acacia pilot bucket ct-esm1-6: output000/ .. output171/ hold model
# years 1850 .. 2021. The ocean (MOM) writes one variable per file, one file
# per model year: output<NNN>/ocean/<stem>-y_<YYYY>.nc, e.g.
# ocean-3d-temp-1mon-mean-y_1850.nc (12 months x 50 levels). One dataset per
# file stem; the plan is `gdal mdim mosaic` along time.
#
#   ESM16_STEM=ocean-3d-temp-1mon-mean   file stem (ACCESS output spec name)
#   ESM16_VAR=temp                       the array in the file
#   ESM16_FIRST, ESM16_LAST              inclusive model years (default all);
#                                        a subset gets its own DATASET name
#   ESM16_LIST=corpus (default)          file list from the aad-filelist
#                                        corpus (source pawsey_ct_esm1_6),
#                                        with the build record for the stale
#                                        step
#   ESM16_LIST=direct                    file names generated from the years,
#                                        for a run before the corpus lists
#                                        the bucket (no build record)
#   ESM16_GRID=1 (default)               add the 2D cell centres geolon_t and
#                                        geolat_t from the static files
#                                        output000/ocean/ocean-2d-geol*_t-fx.nc
#                                        (py/plan_join.py). MOM's grid is
#                                        tripolar: the 1D xt_ocean/yt_ocean
#                                        are nominal and wrong north of about
#                                        65N. The fx files are the same in
#                                        every outputNNN/ (same etag); 0 leaves
#                                        them out
#
# The bucket is a pilot and is expected to move: sources stay verbatim and a
# new location is one more REMAPS rule.
ESM16_URL=https://projects.pawsey.org.au/ct-esm1-6
ESM16_STEM=${ESM16_STEM:-ocean-3d-temp-1mon-mean}
ESM16_GRID=${ESM16_GRID:-1}
ARRAYS=${ESM16_VAR:-temp}
[ "$ESM16_GRID" = 1 ] && ARRAYS="$ARRAYS geolon_t geolat_t"
DATASET=access-esm1-6.historical.$ESM16_STEM${ESM16_FIRST:+-$ESM16_FIRST}${ESM16_LAST:+-$ESM16_LAST}
# product group (products/access-esm/): the scratch prefix on source.coop
PRODUCT_GROUP=access-esm
ESM16_FX_RX='/output000/ocean/ocean-2d-(geolon_t|geolat_t)-fx\.nc$'
# corpus.py matches --date against the file name only, so no directory here
ESM16_FX_NAME='^ocean-2d-(geolon_t|geolat_t)-fx\.nc$'
# sources.txt: the yearly files, then (ESM16_GRID=1) the two fx files; the
# build record covers both
sources() {
  case "${ESM16_LIST:-corpus}" in
    corpus)
      "$PYTHON" "$HERE/py/corpus.py" --source pawsey_ct_esm1_6 \
        --cache "$WORK/listing.parquet" --meta "$WORK/sources.meta.tsv" \
        --match "/output[0-9]{3}/ocean/$ESM16_STEM-y_[0-9]{4}\.nc\$" \
        --date="-y_([0-9]{4})\.nc\$" \
        ${ESM16_FIRST:+--first "$ESM16_FIRST"} ${ESM16_LAST:+--last "$ESM16_LAST"} \
        --prefix https:// /vsicurl/https://
      if [ "$ESM16_GRID" = 1 ]; then
        "$PYTHON" "$HERE/py/corpus.py" --listing "$WORK/listing.parquet" \
          --meta "$WORK/sources.meta.fx.tsv" --match "$ESM16_FX_RX" --date="$ESM16_FX_NAME" \
          --prefix https:// /vsicurl/https://
        # --listing records no source_id: take it from the yearly record
        local sid; sid=$(awk -F'\t' 'NR == 2 {print $1; exit}' "$WORK/sources.meta.tsv")
        awk -F'\t' -v OFS='\t' -v sid="$sid" 'NR > 1 {$1 = sid; print}' "$WORK/sources.meta.fx.tsv" \
          >> "$WORK/sources.meta.tsv"
        rm -f "$WORK/sources.meta.fx.tsv"
      fi ;;
    direct)
      local y
      for y in $(seq "${ESM16_FIRST:-1850}" "${ESM16_LAST:-2021}"); do
        printf '/vsicurl/%s/output%03d/ocean/%s-y_%s.nc\n' "$ESM16_URL" $((y - 1850)) "$ESM16_STEM" "$y"
      done
      if [ "$ESM16_GRID" = 1 ]; then
        printf '/vsicurl/%s/output000/ocean/ocean-2d-%s-fx.nc\n' "$ESM16_URL" geolon_t "$ESM16_URL" geolat_t
      fi ;;
    *) echo "ESM16_LIST must be corpus or direct" >&2; return 1 ;;
  esac
}
# the yearly files mosaicked along time, then the fx arrays joined
make_plan() {
  grep -v -- '-fx\.nc$' "$WORK/sources.txt" > "$WORK/sources.years.txt"
  "$GDAL" mdim mosaic --overwrite --array "${ESM16_VAR:-temp}" "@$WORK/sources.years.txt" "$WORK/plan.vrt"
  if [ "$ESM16_GRID" = 1 ]; then
    local j=() f
    while read -r f; do
      case $f in *geolon_t-fx.nc) j+=(--source "$f:geolon_t") ;; *geolat_t-fx.nc) j+=(--source "$f:geolat_t") ;; esac
    done < <(grep -- '-fx\.nc$' "$WORK/sources.txt")
    [ ${#j[@]} -eq 4 ] || { echo "make_plan: expected the geolon_t and geolat_t fx files in sources.txt" >&2; return 1; }
    "$PYTHON" "$HERE/py/plan_join.py" --plan "$WORK/plan.vrt" --gdal "$GDAL" "${j[@]}"
  fi
}
# target|prefix|replacement, applied at publish only (sources stay verbatim)
REMAPS=("public|/vsicurl/https://|https://")
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=gdal
export STAC_LICENSE=${STAC_LICENSE:-other}
export STAC_TITLE=${STAC_TITLE:-ACCESS-ESM1.6 historical $ESM16_STEM (native MOM output, 1 degree)}
# grist rows need a time axis: list the variable, not the 2D grid arrays
export GRIST_ARRAYS=${GRIST_ARRAYS:-${ESM16_VAR:-temp}}
WORKERS=${WORKERS:-8}
