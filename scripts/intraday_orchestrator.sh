#!/usr/bin/env bash
# 盘中编排：交易日历同步、5 分钟板块资金流、30 分钟全市场行情刷新。
#
# 用法：
#   scripts/intraday_orchestrator.sh calendar   # 同步交易日历（每个交易日开盘前一次）
#   scripts/intraday_orchestrator.sh fundflow   # 抓一次板块资金流快照（仅交易时段）
#   scripts/intraday_orchestrator.sh quotes     # 刷新当天全市场行情并重建三个盘后模块
#
# 由 scripts/install_intraday_cron.sh 写入的 crontab 调用。脚本自己判断是否落在
# 交易时段：时段外直接以 0 退出，不产生噪声日志、也不会让 cron 发失败邮件。
# 真正的交易日判定（节假日、停牌日）由 Django 命令自己完成 —— 这里只做时间粗筛。
set -uo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_ROOT="${REPOSITORY_ROOT}/backend"
LOG_DIR="${INTRADAY_LOG_DIR:-${BACKEND_ROOT}/data/intraday-logs}"

# 优先使用仓库内虚拟环境；调用方可显式覆盖 PYTHON_BIN。
if [ -z "${PYTHON_BIN:-}" ]; then
    if [ -x "${REPOSITORY_ROOT}/.venv/bin/python" ]; then
        PYTHON_BIN="${REPOSITORY_ROOT}/.venv/bin/python"
    else
        PYTHON_BIN="python"
    fi
fi

export TZ="${TZ:-Asia/Shanghai}"

mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/$(date '+%F').log"

usage() {
    echo "usage: $(basename "$0") {calendar|fundflow|quotes}" >&2
}

current_hm() {
    # 10# 前缀：避免 09xx 被当成八进制。
    echo "$((10#$(date '+%H%M')))"
}

# A 股连续交易时段：09:30-11:30 与 13:00-15:00。
in_trading_window() {
    local hm
    hm="$(current_hm)"
    if [ "${hm}" -ge 930 ] && [ "${hm}" -le 1130 ]; then
        return 0
    fi
    if [ "${hm}" -ge 1300 ] && [ "${hm}" -le 1500 ]; then
        return 0
    fi
    return 1
}

today() {
    date '+%F'
}

# 从 .env 读启用的业务模块；缺失时回落到四个默认模块。
enabled_modules() {
    local raw
    raw="$(sed -n 's/^ENABLED_MODULES=//p' "${REPOSITORY_ROOT}/.env" 2>/dev/null | tail -1)"
    if [ -z "${raw}" ]; then
        echo "kaipanla stock_moves sector_momentum hundred_day"
        return 0
    fi
    echo "${raw}" | tr ',' ' '
}

run_step() {
    local name="$1"
    shift
    echo "[$(date '+%F %T')] ${name}: manage.py $*" >>"${LOG_FILE}"
    "${PYTHON_BIN}" manage.py "$@" >>"${LOG_FILE}" 2>&1
    local status=$?
    if [ "${status}" -ne 0 ]; then
        echo "[$(date '+%F %T')] ${name}: FAILED (exit ${status})" >>"${LOG_FILE}"
    fi
    return "${status}"
}

module_enabled() {
    local wanted="$1"
    local module
    for module in $(enabled_modules); do
        if [ "${module}" = "${wanted}" ]; then
            return 0
        fi
    done
    return 1
}

step_calendar() {
    cd "${BACKEND_ROOT}" || return 1
    run_step calendar sync_trading_calendar
}

step_fundflow() {
    if ! in_trading_window; then
        echo "[$(date '+%F %T')] fundflow: outside the trading window, skipped" >>"${LOG_FILE}"
        return 0
    fi
    if ! module_enabled kaipanla; then
        echo "[$(date '+%F %T')] fundflow: kaipanla module is disabled, skipped" >>"${LOG_FILE}"
        return 0
    fi
    cd "${BACKEND_ROOT}" || return 1
    run_step fundflow fetch_kaipanla_sector_fund_flow
}

step_quotes() {
    local day="$1"
    cd "${BACKEND_ROOT}" || return 1

    if ! run_step quotes refresh_intraday_quotes --date "${day}"; then
        # 行情没刷新成功就不重建产物：重建只会把同一份旧输入再算一遍。
        return 1
    fi

    local failures=0
    if module_enabled stock_moves; then
        run_step stock_moves build_stock_moves --date "${day}" || failures=$((failures + 1))
    fi
    if module_enabled sector_momentum; then
        run_step sector_momentum build_sector_momentum --date "${day}" || failures=$((failures + 1))
    fi
    if module_enabled hundred_day; then
        run_step hundred_day build_hundred_day --date "${day}" || failures=$((failures + 1))
    fi
    if [ "${failures}" -ne 0 ]; then
        echo "[$(date '+%F %T')] quotes: ${failures} derived build(s) failed" >>"${LOG_FILE}"
        return 1
    fi
    return 0
}

case "${1:-}" in
    calendar)
        step_calendar
        ;;
    fundflow)
        step_fundflow
        ;;
    quotes)
        step_quotes "$(today)"
        ;;
    *)
        usage
        exit 2
        ;;
esac
