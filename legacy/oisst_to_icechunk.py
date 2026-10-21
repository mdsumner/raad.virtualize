"""
STAGE 3: kerchunk-parquet -> Icechunk, WITHOUT re-parsing any netCDF.

VirtualiZarr's KerchunkParquetParser re-opens the refs you already built in
stage 2 (from the VRT + generic store), so its only job is transcoding to the
Icechunk format. The referenced OISST bytes are reached at Icechunk read-time
via a VirtualChunkContainer pointing at the anonymous NOAA S3 bucket.

  requires: virtualizarr >= 2.5, icechunk, obstore
  note: refs must use s3:// URLs (fsspec/obstore), NOT /vsis3 (that's GDAL-only).
"""
import icechunk as ic
from virtualizarr import open_virtual_dataset
from virtualizarr.parsers import KerchunkParquetParser
from obstore.store import from_url
from obspec_utils.registry import ObjectStoreRegistry

KERCHUNK = "s3://aad-index/oisst/oisst.parquet"          # STORE #2 (stage 2 output)
NOAA     = "s3://noaa-cdr-sea-surface-temp-optimum-interpolation-pds/"  # ref target; TRAILING SLASH required
ICE      = "aad-index"                                    # STORE #3 target bucket

# registry to READ the kerchunk-parquet manifest itself (lives on aad-index)
registry = ObjectStoreRegistry({
    "s3://aad-index/": from_url("s3://aad-index/", region="ap-southeast-2"),  # Pawsey Acacia
})

vds = open_virtual_dataset(
    url=KERCHUNK,
    parser=KerchunkParquetParser(),
    registry=registry,
)

# Icechunk repo: a virtual-chunk container maps the NOAA prefix -> anonymous S3,
# so reads of the virtual chunks resolve against the public bucket.
config = ic.RepositoryConfig.default()
config.set_virtual_chunk_container(ic.VirtualChunkContainer(
    url_prefix=NOAA,
    store=ic.s3_store(region="us-east-1", anonymous=True),
))

storage = ic.s3_storage(bucket=ICE, prefix="oisst/icechunk", region="ap-southeast-2")
repo    = ic.Repository.create(storage, config)          # or .open_or_create for updates
session = repo.writable_session("main")

vds.vz.to_icechunk(session.store)                        # transcode, no re-scan
session.commit("OISST virtual store from kerchunk-parquet")
# STORE #3 published. Later daily updates: repo.writable_session, to_icechunk(
#   append_dim="time"), commit -- Icechunk owns the transactional update from here.
