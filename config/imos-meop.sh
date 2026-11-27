# IMOS Animal Tracking Facility (AATAMS) satellite-relay tag CTD profiles,
# MEOP-QC'd: southern elephant seals, Weddell seals, fur seals and turtles.
# One classic netCDF file (CDF-1, Argo profile format) per tag on the IMOS
# public bucket, s3://imos-data/IMOS/AATAMS/satellite_tagging/MEOP_QC_CTD/
# (ap-southeast-2), mirrored on NCI in /g/data/sh74/IMOS_AODN/IMOS/AATAMS/.
# Two releases share the prefix:
#   IMOS-CTD_2024        *_hr1_prof.nc, 265 files (one MEOP-CTD_2023-12-01),
#                        N_LEVELS 1000 (1 dbar), 2012-2024
#   MEOP-CTD_2017-10-01  the other *_prof.nc, 299 files, N_LEVELS 12 to 28
#                        (fixed SRDL levels, by tag), 2004-2017
# The files are rewritten in place (299 last written in 2017, 135 in 2024,
# 130 in 2025): the build record keeps each file's ETag under the corpus
# source imos_aatams_meop_ctd (aad-filelist, s3-list of the same prefix), so
#   bash run.sh config/imos-meop.sh stale
# lists those changed since the build against the corpus, and
#   python py/s3_sources.py --bucket imos-data --region ap-southeast-2 \
#     --prefix "$MEOP_PREFIX" --stale work/<DATASET>/sources.meta.tsv
# does the same against the bucket now.
#
#   MEOP_CANON=cube (default)  meop-ctd-2024: the 2024 release as one cube of
#       (N_PROF, N_LEVELS) = (126518, 1000), every file's profiles in key
#       order (py/plan_concat.py), one profile a chunk (4000 bytes). The
#       per-profile variables (MEOP_INLINE: time, position, cycle, flags)
#       are inline arrays; `tag` (the file of each profile, names in its
#       attribute source_names) and `row` (the profile's row in that file)
#       are derived. Per-level QC flags (*_QC, all '1' where a value is
#       present and '9' elsewhere in the files checked) and the text
#       variables are left out: GDAL reads a 2D char variable as strings.
#   MEOP_CANON=tags            meop-ctd-tags: every file of both releases as a
#       group named for its tag (ct36-B-09; py/plan_groups.py), every
#       variable as stored (QC flags and text as char) and the file's
#       global attributes, each variable one chunk (one byte range). The
#       Zarr forms read char variables as netCDF does (xarray joins the last
#       dimension into strings); the VRT leaves out 2D char variables.
#
# No position screen enters the store: the extents of the STAC items use
# positions south of the equator only (MEOP_LAT_MAX, default 0; every
# species here is southern, and 19,484 profiles of five campaigns are
# placed in the northern hemisphere with POSITION_QC 1).
MEOP_CANON=${MEOP_CANON:-cube}
MEOP_BUCKET=imos-data
MEOP_REGION=ap-southeast-2
MEOP_PREFIX=IMOS/AATAMS/satellite_tagging/MEOP_QC_CTD/
MEOP_HTTPS=https://$MEOP_BUCKET.s3.$MEOP_REGION.amazonaws.com/
MEOP_LAT_MAX=${MEOP_LAT_MAX:-0}
# product group (products/imos-tracking/): the scratch prefix on source.coop
PRODUCT_GROUP=imos-tracking
case $MEOP_CANON in
  cube)
    DATASET=meop-ctd-2024
    MEOP_MATCH=${MEOP_MATCH:-'_hr1_prof\.nc$'}
    ARRAYS=""
    for v in PRES TEMP PSAL CHLA DOXY LIGHT; do ARRAYS="$ARRAYS $v ${v}_ADJUSTED ${v}_ADJUSTED_ERROR"; done
    ARRAYS=${ARRAYS# }
    MEOP_INLINE=${MEOP_INLINE:-JULD JULD_QC JULD_LOCATION LATITUDE LONGITUDE POSITION_QC CYCLE_NUMBER DATA_MODE DIRECTION PROFILE_PRES_QC PROFILE_TEMP_QC PROFILE_PSAL_QC PROFILE_CHLA_QC PROFILE_DOXY_QC PROFILE_LIGHT_QC}
    export STAC_TITLE="${STAC_TITLE:-IMOS satellite-relay tag CTD profiles (MEOP quality control), IMOS-CTD_2024 release, one cube of profiles by 1 dbar levels}"
    export STAC_LICENSE=${STAC_LICENSE:-CC-BY-4.0}
    # thumbnail: temperature of a Kerguelen elephant seal (2020, 1045
    # profiles), profiles across and levels down
    export STAC_THUMB_ARRAY=${STAC_THUMB_ARRAY:-TEMP_ADJUSTED}
    export STAC_THUMB_SOURCE=${STAC_THUMB_SOURCE:-/ct160-264-20_hr1_prof[.]nc\$}
    export STAC_THUMB_TRANSPOSE=${STAC_THUMB_TRANSPOSE:-1}
    # one manifest per array: at the default split (365 profiles) the cube
    # would be about 6,200 small manifest objects
    ICECHUNK_ARGS=${ICECHUNK_ARGS:---split 0}
    ;;
  tags)
    DATASET=meop-ctd-tags
    MEOP_MATCH=${MEOP_MATCH:-'_prof\.nc$'}
    # every array of the plan (about 27,000: harvest.py --array @plan)
    ARRAYS=@plan
    export STAC_TITLE="${STAC_TITLE:-IMOS satellite-relay tag CTD profiles (MEOP quality control), both releases, one group per tag}"
    # IMOS-CTD_2024 files state CC-BY-4.0; MEOP-CTD_2017-10-01 files the MEOP
    # data policy (distribution_statement)
    export STAC_LICENSE=${STAC_LICENSE:-other}
    export STAC_THUMB_ARRAY=${STAC_THUMB_ARRAY:-ct160-264-20/TEMP_ADJUSTED}
    export STAC_THUMB_TRANSPOSE=${STAC_THUMB_TRANSPOSE:-1}
    # one-chunk arrays: one ref per kerchunk Parquet file, not 100000 padded
    export KERCHUNK_RECORD_SIZE=${KERCHUNK_RECORD_SIZE:-1}
    ;;
  *) echo "imos-meop.sh: MEOP_CANON must be cube or tags" >&2; return 1 ;;
esac

sources() {
  "$PYTHON" "$HERE/py/s3_sources.py" --bucket "$MEOP_BUCKET" --region "$MEOP_REGION" \
    --prefix "$MEOP_PREFIX" --match "$MEOP_MATCH" --meta "$WORK/sources.meta.tsv" \
    --source-id imos_aatams_meop_ctd
}
make_plan() {
  local ext=(--extents "$WORK/extents.tsv" --lat LATITUDE --lon LONGITUDE --time JULD --lat-max "$MEOP_LAT_MAX")
  if [ "$MEOP_CANON" = tags ]; then
    "$PYTHON" "$HERE/py/plan_groups.py" --sources "$WORK/sources.txt" --strip '_(hr1_)?prof$' \
      "${ext[@]}" --workers "$WORKERS" "$WORK/plan.vrt"
    return
  fi
  local a=() v
  for v in $ARRAYS; do a+=(--array "$v"); done
  for v in $MEOP_INLINE; do a+=(--inline "$v"); done
  "$PYTHON" "$HERE/py/plan_concat.py" --sources "$WORK/sources.txt" --dim N_PROF "${a[@]}" \
    --index tag --row row "${ext[@]}" --workers "$WORKERS" "$WORK/plan.vrt"
}
# per-tag bbox and time range of the STAC items (--extents of the planners)
export STAC_EXTENTS=${STAC_EXTENTS:-${E2E_WORK:-$HERE/work/$DATASET}/extents.tsv}
# target|prefix|replacement, applied at publish only (sources stay verbatim):
# public https, the bucket as s3://, and the NCI mirror for jobs on Gadi
REMAPS=("public|/vsicurl/https://|https://"
        "s3|/vsicurl/$MEOP_HTTPS|s3://$MEOP_BUCKET/"
        "nci|/vsicurl/$MEOP_HTTPS|/g/data/sh74/IMOS_AODN/")
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=gdal
# one item per tag (265 or 564): ndjson and stac-geoparquet only
export STAC_ITEM_FILES=${STAC_ITEM_FILES:-0}
# no time axis on a grid, so no grist catalog
DEFAULT_STEPS="plan harvest collate assert render icechunk stac verify"
WORKERS=${WORKERS:-16}
