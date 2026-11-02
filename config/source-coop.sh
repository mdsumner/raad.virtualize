# Publish target: a source.coop product, over the S3 API of the source.coop
# data proxy (data.source.coop, path style; the bucket is the account).
# Source after the dataset config:
#   bash run.sh config/ghrsst-cog.sh config/source-coop.sh publish verify-published
# Outputs land under
#   /vsis3/$SOURCECOOP_REPO/$SOURCECOOP_PREFIX/<DATASET>/
# (flat/, mdim.vrt, kerchunk/, icechunk/, stac/, plan.vrt, store.sqlite).
# In the scratch product the prefix is the dataset config's PRODUCT_GROUP
# (bluelink/, ghrsst/, oisst/, seaice/), one group per products/<group>/,
# with the root catalog at the product root (catalog.sh products ...).
# Layout, test product and promotion: docs/ghrsst-source-coop.md. Check that
# a product takes writes first with py/sourcecoop_check.py.
#
#   SOURCECOOP_REPO    account/product, default ausantarctic/ausantarctic-scratch,
#                      the drafting product for every index family (GHRSST,
#                      bluelink, others). Any other ausantarctic/ product is
#                      a production product and is refused unless
#                      SOURCECOOP_PRODUCTION=1
#   SOURCECOOP_PREFIX  default PRODUCT_GROUP in the scratch product (set by
#                      the dataset config), virtual in a production product
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
if [ -z "${SOURCECOOP_PREFIX:-}" ]; then
  if [ "$SOURCECOOP_REPO" = "$SOURCECOOP_SCRATCH" ]; then
    # a dataset with no group would land at the product root, beside the
    # root catalog; catalog.sh for the root itself runs with DATASET empty
    if [ -z "${PRODUCT_GROUP:-}" ] && [ -n "${DATASET:-}" ]; then
      echo "source-coop.sh: $DATASET has no PRODUCT_GROUP; set it in the dataset config or set SOURCECOOP_PREFIX" >&2
      exit 1
    fi
    SOURCECOOP_PREFIX=${PRODUCT_GROUP:-}
  else
    SOURCECOOP_PREFIX=virtual
  fi
fi
SOURCECOOP_PREFIX=${SOURCECOOP_PREFIX%/}
SOURCECOOP_PREFIX=${SOURCECOOP_PREFIX#/}
if [[ $SOURCECOOP_REPO == ausantarctic/* && $SOURCECOOP_REPO != "$SOURCECOOP_SCRATCH" && \
      ${SOURCECOOP_PRODUCTION:-0} != 1 ]]; then
  echo "source-coop.sh: $SOURCECOOP_REPO is a production product; drafts go to $SOURCECOOP_SCRATCH, set SOURCECOOP_PRODUCTION=1 to write there" >&2
  exit 1
fi
SOURCECOOP_ENDPOINT=${SOURCECOOP_ENDPOINT:-data.source.coop}
# PUBLISH_ROOT: the product root, where the root catalog of the groups sits
# (catalog.sh products); PUBLISH: the group, where its datasets and catalog sit
PUBLISH_ROOT=/vsis3/$SOURCECOOP_REPO
PUBLISH_ROOT_BASE=https://$SOURCECOOP_ENDPOINT/$SOURCECOOP_REPO
PUBLISH=$PUBLISH_ROOT${SOURCECOOP_PREFIX:+/$SOURCECOOP_PREFIX}
# absolute STAC asset hrefs and GDAL open strings at the public URL
STAC_BASE=${STAC_BASE:-$PUBLISH_ROOT_BASE${SOURCECOOP_PREFIX:+/$SOURCECOOP_PREFIX}/$DATASET}
# the proxy accepts any region; CPL_AWS_WEB_IDENTITY_ENABLE=NO keeps GDAL
# from sending a service-account key file to AWS STS instead of the proxy
export AWS_S3_ENDPOINT=$SOURCECOOP_ENDPOINT AWS_HTTPS=YES AWS_VIRTUAL_HOSTING=FALSE \
       CPL_AWS_WEB_IDENTITY_ENABLE=NO
export AWS_REGION=${AWS_REGION:-us-west-2}
PUBLISH_WITH=obstore
