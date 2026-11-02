# Publish target: a source.coop product, over the S3 API of the source.coop
# data proxy (data.source.coop, path style; the bucket is the account).
# Source after the dataset config:
#   bash run.sh config/ghrsst-cog.sh config/source-coop.sh publish verify-published
# Outputs land under
#   /vsis3/$SOURCECOOP_REPO/$SOURCECOOP_PREFIX/<DATASET>/
# (flat/, mdim.vrt, kerchunk/, icechunk/, stac/, plan.vrt, store.sqlite).
# Layout, test product and promotion: docs/ghrsst-source-coop.md. Check that
# a product takes writes first with py/sourcecoop_check.py.
#
#   SOURCECOOP_REPO    account/product, default ausantarctic/ausantarctic-scratch,
#                      the drafting product for every index family (GHRSST,
#                      bluelink, others). Any other ausantarctic/ product is
#                      a production product and is refused unless
#                      SOURCECOOP_PRODUCTION=1
#   SOURCECOOP_PREFIX  default virtual
#   SOURCECOOP_ENDPOINT  default data.source.coop
#
# The data proxy rejects GDAL /vsis3/ writes ("missing SignedHeaders"), so
# publish goes through py/s3_sync.py (obstore; pip install obstore). GDAL
# anonymous reads work, so verify-published is unchanged.
#
# Credentials are NOT kept here. For publish export the product's temporary
# key set (product page, "View Credentials", or `source-coop creds`):
# AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and AWS_SESSION_TOKEN. They last
# one hour; a publish that runs longer fails with ExpiredToken.
# verify-published needs no keys: with AWS_NO_SIGN_REQUEST=YES it reads the
# forms back anonymously, as a public reader would.
SOURCECOOP_SCRATCH=ausantarctic/ausantarctic-scratch
SOURCECOOP_REPO=${SOURCECOOP_REPO:-$SOURCECOOP_SCRATCH}
SOURCECOOP_REPO=${SOURCECOOP_REPO%/}
SOURCECOOP_PREFIX=${SOURCECOOP_PREFIX:-virtual}
SOURCECOOP_PREFIX=${SOURCECOOP_PREFIX%/}
SOURCECOOP_PREFIX=${SOURCECOOP_PREFIX#/}
if [[ $SOURCECOOP_REPO == ausantarctic/* && $SOURCECOOP_REPO != "$SOURCECOOP_SCRATCH" && \
      ${SOURCECOOP_PRODUCTION:-0} != 1 ]]; then
  echo "source-coop.sh: $SOURCECOOP_REPO is a production product; drafts go to $SOURCECOOP_SCRATCH, set SOURCECOOP_PRODUCTION=1 to write there" >&2
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
PUBLISH_WITH=obstore
