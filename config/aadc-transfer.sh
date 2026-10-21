# Publish target: AADC transfer bucket (S3 compatible, path-style, HTTPS).
# Source after the dataset config:
#   bash run.sh config/bran.sh config/aadc-transfer.sh publish verify-published
# Outputs land under $PUBLISH/<DATASET>/: flat/, mdim.vrt, kerchunk/, icechunk/,
# plan.vrt, store.sqlite. Credentials are NOT kept here: export
# AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY (or AWS_PROFILE) yourself.
AADC_PREFIX=${AADC_PREFIX:-michae_sum/e2e}
PUBLISH=/vsis3/aadc-transfer/$AADC_PREFIX
export AWS_S3_ENDPOINT=transfer.data.aad.gov.au AWS_HTTPS=YES AWS_VIRTUAL_HOSTING=FALSE
export AWS_REGION=${AWS_REGION:-us-east-1}
