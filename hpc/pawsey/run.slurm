#!/bin/bash --login
#SBATCH --job-name=rv-run
#SBATCH --account=pawsey1362
#SBATCH --partition=work
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --time=01:00:00
#SBATCH --output=rv-run-%j.out
#
# run.sh inside the image on Pawsey Setonix as a batch job, sized for the
# byte harvest (hpc/pawsey/singularity-run.sh does the container work).
# From the repository root:
#
#   sbatch --export=ALL,RUN_ARGS="config/esacci-oc.sh config/source-coop.sh" hpc/pawsey/run.slurm
#   sbatch --export=ALL,ESACCI_CADENCE=5day,RUN_ARGS="config/esacci-oc.sh plan harvest" hpc/pawsey/run.slurm
#
#   RUN_ARGS  the run.sh arguments: config files, then steps (required)
#   WORKERS   harvest processes (default: the job's hardware threads, 8 for
#             the 4 cores above)
#
# Sizing (2026-11-06, ESA CCI 5-day, 2126 COGs, 471,972 chunk rows): the
# harvest of local COGs takes 14 s with 8 workers on 4 cores and 12 s with
# 32, so 4 cores is the default. On Setonix a Slurm CPU is a hardware
# thread (two per core), memory defaults to 920 MB per thread, and billing
# counts CPUs only, but a --mem request adds cores until the memory fits:
# 24 cpus with --mem=96G was allocated 54 cores and billed 108. Leave --mem
# out unless a step needs it. No step of that build did: collate 0.9 GB
# (36 s), render 0.8 GB (18 s), icechunk 0.9 GB (4 s), verify 2.2 GB (33 s),
# all inside the 7.4 GB default of 8 threads. A much larger store (GHRSST MUR,
# BRAN) may need more: check MaxRSS with sacct after its first build.
#
# Publish steps belong on a login node (the source.coop keys last one hour).
# Source the publish config at build time too (config/source-coop.sh), so
# the grist and STAC steps write public URLs, not local paths.
set -uo pipefail
cd "${SLURM_SUBMIT_DIR:-$PWD}"
[ -n "${RUN_ARGS:-}" ] || { echo "run.slurm: set RUN_ARGS (run.sh arguments)" >&2; exit 1; }
export WORKERS=${WORKERS:-${SLURM_CPUS_ON_NODE:-8}}
echo "run.slurm: WORKERS=$WORKERS on ${SLURM_CPUS_ON_NODE:-?} threads; run.sh $RUN_ARGS"
# shellcheck disable=SC2086  # RUN_ARGS is a word list
exec bash hpc/pawsey/singularity-run.sh run.sh $RUN_ARGS
