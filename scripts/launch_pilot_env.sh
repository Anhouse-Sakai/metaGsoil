set -euo pipefail
ROOT="${LITTLEDREAM_ROOT:-$PWD}"
cd "$ROOT"
mkdir -p download_logs/environment
nohup bash scripts/install_pilot_env.sh > download_logs/environment/install.log 2>&1 < /dev/null &
pid=$!
printf '%s\n' "$pid" > download_logs/environment/install.pid
printf 'started\t%s\n' "$pid"
