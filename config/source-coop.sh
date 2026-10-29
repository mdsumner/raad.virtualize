# Publish target: a source.coop product, over the S3 API of the source.coop
# data proxy (data.source.coop, path style; the bucket is the account).
# Source after the dataset config:
#   SOURCECOOP_REPO=mdsumner/ghrsst-mur-virtual-test SOURCECOOP_PREFIX=virtual \
#     bash run.sh config/ghrsst-cog.sh config/source-coop.sh publish verify-published
# Outputs land under
#   /vsis3/$SOURCECOOP_REPO/$SOURCECOOP_PREFIX/<DATASET>/
# (flat/, mdim.vrt, kerchunk/, icechunk/, stac/, plan.vrt, store.sqlite).
# Layout, test product and promotion: docs/ghrsst-source-coop.md. Check that
# a product takes writes first with py/sourcecoop_check.py.
#
#   SOURCECOOP_REPO    account/product, default ausantarctic/ghrsst-mur-v2
#   SOURCECOOP_PREFIX  required. In the production product
#                      (ausantarctic/ghrsst-mur-v2) it must be dev or start
#                      with dev/ unless SOURCECOOP_PRODUCTION=1; any prefix
#                      is accepted in another product
#   SOURCECOOP_ENDPOINT  default data.source.coop
#
# Credentials are NOT kept here. For publish export the product's temporary
# key set (product page, "View Credentials", or `source-coop creds`):
# AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and AWS_SESSION_TOKEN. They last
# one hour and GDAL keeps the first set it reads, so a publish that runs
# longer fails with ExpiredToken: publish in parts, or with the AWS CLI.
# verify-published needs no keys: with AWS_NO_SIGN_REQUEST=YES it reads the
# forms back anonymously, as a public reader would.
SOURCECOOP_REPO=${SOURCECOOP_REPO:-ausantarctic/ghrsst-mur-v2}
SOURCECOOP_REPO=${SOURCECOOP_REPO%/}
: "${SOURCECOOP_PREFIX:?set SOURCECOOP_PREFIX, for example dev/virtual}"
SOURCECOOP_PREFIX=${SOURCECOOP_PREFIX%/}
SOURCECOOP_PREFIX=${SOURCECOOP_PREFIX#/}
if [[ $SOURCECOOP_REPO == ausantarctic/ghrsst-mur-v2 && $SOURCECOOP_PREFIX != dev && \
      $SOURCECOOP_PREFIX != dev/* && ${SOURCECOOP_PRODUCTION:-0} != 1 ]]; then
  echo "source-coop.sh: prefix '$SOURCECOOP_PREFIX' in $SOURCECOOP_REPO is outside dev/; set SOURCECOOP_PRODUCTION=1 to write there" >&2
  exit 1
fi
SOURCECOOP_ENDPOINT=${SOURCECOOP_ENDPOINT:-data.source.coop}
PUBLISH=/vsis3/$SOURCECOOP_REPO/$SOURCECOOP_PREFIX
# absolute STAC asset hrefs and GDAL open strings at the public URL
STAC_BASE=${STAC_BASE:-https://$SOURCECOOP_ENDPOINT/$SOURCECOOP_REPO/$SOURCECOOP_PREFIX/$DATASET}
# the proxy accepts any region; CPL_AWS_WEB_IDENTITY_ENABLE=NO keeps GDAL
# from sending a service-account key file to AWS STS instead of the proxy
export AWS_S3_ENDPOINT=$SOURCECOOP_ENDPOINT AWS_HTTPS=YES AWS_VIRTUAL_HOSTING=FALSE \
       CPL_AWS_WEB_IDENTITY_ENABLE=NO
export AWS_REGION=${AWS_REGION:-us-west-2}
