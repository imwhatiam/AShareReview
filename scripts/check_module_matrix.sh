#!/usr/bin/env bash
# Validate that each business app remains deployable with only core enabled.
# This performs no upstream collection. Set RUN_UPSTREAM_DRY_RUNS=1 only in an
# approved environment where test requests to configured upstream sources are allowed.
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_ROOT="${REPOSITORY_ROOT}/backend"
PYTHON_BIN="${PYTHON_BIN:-python}"

cd "${BACKEND_ROOT}"

command_for_module() {
    case "$1" in
        kaipanla) echo 'fetch_kaipanla_sector_fund_flow' ;;
        eastmoney) echo 'fetch_eastmoney_sector_fund_flow' ;;
        stock_moves) echo 'build_stock_moves' ;;
        sector_momentum) echo 'build_sector_momentum' ;;
        hundred_day) echo 'build_hundred_day' ;;
        *)
            echo "Unknown module: $1" >&2
            return 1
            ;;
    esac
}

route_for_module() {
    case "$1" in
        kaipanla|eastmoney) echo 'sectors/' ;;
        stock_moves|sector_momentum|hundred_day) echo '' ;;
        *)
            echo "Unknown module: $1" >&2
            return 1
            ;;
    esac
}

for module in kaipanla eastmoney stock_moves sector_momentum hundred_day; do
    command_name="$(command_for_module "${module}")"
    route_suffix="$(route_for_module "${module}")"
    echo "== ${module}: Django configuration =="
    ENABLED_MODULES="${module}" "${PYTHON_BIN}" manage.py check

    echo "== ${module}: migration routing =="
    ENABLED_MODULES="${module}" "${PYTHON_BIN}" manage.py migrate --plan --database=default core
    ENABLED_MODULES="${module}" "${PYTHON_BIN}" manage.py migrate --plan --database="${module}" "${module}"

    echo "== ${module}: command and URL discovery =="
    ENABLED_MODULES="${module}" "${PYTHON_BIN}" manage.py help "${command_name}" >/dev/null
    ENABLED_MODULES="${module}" "${PYTHON_BIN}" manage.py shell -c "
from django.urls import Resolver404, resolve
match = resolve('/api/${module//_/-}/${route_suffix}')
assert match.namespace == '${module}', match.namespace
for disabled in {'kaipanla', 'eastmoney', 'stock_moves', 'sector_momentum', 'hundred_day'} - {'${module}'}:
    try:
        resolve('/api/' + disabled.replace('_', '-') + '/')
    except Resolver404:
        continue
    raise AssertionError('Disabled module URL is mounted: ' + disabled)
"

    echo "== ${module}: isolated app test label =="
    ENABLED_MODULES="${module}" "${PYTHON_BIN}" manage.py test "${module}.tests"

done

if [[ "${RUN_UPSTREAM_DRY_RUNS:-0}" == '1' ]]; then
    echo '== approved upstream dry-run checks =='
    ENABLED_MODULES=kaipanla "${PYTHON_BIN}" manage.py fetch_kaipanla_sector_fund_flow --latest --dry-run
    ENABLED_MODULES=eastmoney "${PYTHON_BIN}" manage.py fetch_eastmoney_sector_fund_flow --latest --dry-run
else
    echo 'Skipped upstream dry-runs (set RUN_UPSTREAM_DRY_RUNS=1 only after explicit approval).'
fi
