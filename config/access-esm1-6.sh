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
#
# The bucket is a pilot and is expected to move: sources stay verbatim and a
# new location is one more REMAPS rule.
ESM16_URL=https://projects.pawsey.org.au/ct-esm1-6
ESM16_STEM=${ESM16_STEM:-ocean-3d-temp-1mon-mean}
ARRAYS=${ESM16_VAR:-temp}
DATASET=access-esm1-6.historical.$ESM16_STEM${ESM16_FIRST:+-$ESM16_FIRST}${ESM16_LAST:+-$ESM16_LAST}
sources() {
  case "${ESM16_LIST:-corpus}" in
    corpus)
      "$PYTHON" "$HERE/py/corpus.py" --source pawsey_ct_esm1_6 \
        --cache "$WORK/listing.parquet" --meta "$WORK/sources.meta.tsv" \
        --match "/output[0-9]{3}/ocean/$ESM16_STEM-y_[0-9]{4}\.nc\$" \
        --date="-y_([0-9]{4})\.nc\$" \
        ${ESM16_FIRST:+--first "$ESM16_FIRST"} ${ESM16_LAST:+--last "$ESM16_LAST"} \
        --prefix https:// /vsicurl/https:// ;;
    direct)
      local y
      for y in $(seq "${ESM16_FIRST:-1850}" "${ESM16_LAST:-2021}"); do
        printf '/vsicurl/%s/output%03d/ocean/%s-y_%s.nc\n' "$ESM16_URL" $((y - 1850)) "$ESM16_STEM" "$y"
      done ;;
    *) echo "ESM16_LIST must be corpus or direct" >&2; return 1 ;;
  esac
}
# target|prefix|replacement, applied at publish only (sources stay verbatim)
REMAPS=("public|/vsicurl/https://|https://")
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=gdal
# no source.coop product yet: no grist or STAC step by default
DEFAULT_STEPS=${DEFAULT_STEPS:-plan harvest collate render icechunk verify}
WORKERS=${WORKERS:-8}
