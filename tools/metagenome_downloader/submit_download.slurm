#!/usr/bin/env bash
#SBATCH --job-name=meta_download
#SBATCH --cpus-per-task=16
#SBATCH --mem=16G
#SBATCH --time=7-00:00:00
#SBATCH --output=meta_download.%j.log
#SBATCH --error=meta_download.%j.err

set -euo pipefail

BUNDLE_DIR="${BUNDLE_DIR:-$PWD/metagenome_downloader_bundle}"
OUTDIR="${OUTDIR:-$PWD/metagenome_downloads}"

export JOBS="${SLURM_CPUS_PER_TASK:-4}"
export CONNECTIONS=4
export THREADS="${SLURM_CPUS_PER_TASK:-16}"

bash "$BUNDLE_DIR/run_download.sh" "$OUTDIR"
