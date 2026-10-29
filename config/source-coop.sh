# Publish target: a source.coop repository, over the S3 API of the
# source.coop data proxy (data.source.coop, path style). Source after the
# dataset config:
#   SOURCECOOP_PREFIX=dev/virtual bash run.sh config/ghrsst-cog.sh \
#     config/source-coop.sh publish verify-published
# Outputs land under
#   /vsis3/$SOURCECOOP_REPO/$SOURCECOOP_PREFIX/<DATASET>/
# (flat/, mdim.vrt, kerchunk/, icechunk/, stac/, plan.vrt, store.sqlite).
# Layout and promotion: docs/ghrsst-source-coop.md.
#
#   SOURCECOOP_REPO    account/repository, default ausantarctic/ghrsst-mur-v2
#   SOURCECOOP_PREFIX  required; must be dev or start with dev/ unless
#                      SOURCECOOP_PRODUCTION=1 (the guard keeps a trial run
#                      out of the production layout)
#   SOURCECOOP_ENDPOINT  default data.source.coop
#
# Credentials are NOT kept here: export the source.coop API key pair as
# AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY for publish. verify-published
# needs no keys: with AWS_NO_SIGN_REQUEST=YES it reads the forms back
# anonymously, as a public reader would.
SOURCECOOP_REPO=${SOURCECOOP_REPO:-ausantarctic/ghrsst-mur-v2}
: "${SOURCECOOP_PREFIX:?set SOURCECOOP_PREFIX, for example dev/virtual}"
SOURCECOOP_PREFIX=${SOURCECOOP_PREFIX%/}
SOURCECOOP_PREFIX=${SOURCECOOP_PREFIX#/}
if [[ $SOURCECOOP_PREFIX != dev && $SOURCECOOP_PREFIX != dev/* && ${SOURCECOOP_PRODUCTION:-0} != 1 ]]; then
  echo "source-coop.sh: prefix '$SOURCECOOP_PREFIX' is outside dev/; set SOURCECOOP_PRODUCTION=1 to write there" >&2
  exit 1
fi
SOURCECOOP_ENDPOINT=${SOURCECOOP_ENDPOINT:-data.source.coop}
PUBLISH=/vsis3/$SOURCECOOP_REPO/$SOURCECOOP_PREFIX
# absolute STAC asset hrefs and GDAL open strings at the public URL
STAC_BASE=${STAC_BASE:-https://$SOURCECOOP_ENDPOINT/$SOURCECOOP_REPO/$SOURCECOOP_PREFIX/$DATASET}
export AWS_S3_ENDPOINT=$SOURCECOOP_ENDPOINT AWS_HTTPS=YES AWS_VIRTUAL_HOSTING=FALSE
export AWS_REGION=${AWS_REGION:-us-east-1}
