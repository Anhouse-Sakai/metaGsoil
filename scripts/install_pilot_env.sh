set -euo pipefail
ROOT="${LITTLEDREAM_ROOT:-$PWD}"
cd "$ROOT"
mkdir -p 必要软件/micromamba/bin 必要软件/mamba_root download_logs/environment
if [ ! -x 必要软件/micromamba/bin/micromamba ]; then
  tmpdir=$(mktemp -d $ROOT/必要软件/micromamba-download.XXXXXX)
  curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest \
    | tar -xj -C "$tmpdir" bin/micromamba
  install -m 0755 "$tmpdir/bin/micromamba" 必要软件/micromamba/bin/micromamba
  rm -rf "$tmpdir"
fi
export MAMBA_ROOT_PREFIX=$ROOT/必要软件/mamba_root
if [ -x 必要软件/pilot_env/bin/Rscript ]; then
  echo 'pilot_env already exists'
  exit 0
fi
必要软件/micromamba/bin/micromamba create -y -p $ROOT/必要软件/pilot_env \
  -f $ROOT/pilot_environment.yml
$ROOT/必要软件/pilot_env/bin/Rscript -e \
  'pkgs<-c("dada2","ShortRead","Biostrings","vegan","data.table","ggplot2","patchwork","svglite","ragg","ape"); stopifnot(all(vapply(pkgs, requireNamespace, logical(1), quietly=TRUE)))'
必要软件/micromamba/bin/micromamba list -p $ROOT/必要软件/pilot_env \
  --explicit > 必要软件/pilot_env_explicit.txt
echo 'pilot_env_ready'
