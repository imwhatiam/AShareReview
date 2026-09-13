#!/usr/bin/env bash
# 安装/查看/卸载盘中采集的 launchd 用户代理（macOS）。
#
#   scripts/install_intraday_launchd.sh install
#   scripts/install_intraday_launchd.sh uninstall
#   scripts/install_intraday_launchd.sh status
#
# 为什么默认用 launchd 而不是 crontab：macOS 上 /usr/bin/crontab 受 TCC 保护，
# 写入需要给调用进程“完全磁盘访问权限”，否则报 Operation not permitted；用户级
# launchd 代理不需要额外授权。
#
# 三个代理（都调用同一个编排脚本，真正的交易日判定在 Django 命令里）：
#   com.ashare-market-review.intraday.calendar  工作日 09:25 同步交易日历
#   com.ashare-market-review.intraday.fundflow  每 5 分钟（时段外脚本自行跳过）
#   com.ashare-market-review.intraday.quotes    每 30 分钟（时段外脚本自行跳过）
#
# 另有等价的 crontab 方案：scripts/install_intraday_cron.sh。
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORCHESTRATOR="${REPOSITORY_ROOT}/scripts/intraday_orchestrator.sh"
AGENT_DIR="${HOME}/Library/LaunchAgents"
LOG_DIR="${REPOSITORY_ROOT}/backend/data/intraday-logs"
LABEL_PREFIX="com.ashare-market-review.intraday"
NAMES=(calendar fundflow quotes)

detect_python() {
    if [ -x "${REPOSITORY_ROOT}/.venv/bin/python" ]; then
        echo "${REPOSITORY_ROOT}/.venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        command -v python3
    else
        echo "python3"
    fi
}

calendar_schedule() {
    echo '    <key>StartCalendarInterval</key>'
    echo '    <array>'
    local weekday
    for weekday in 1 2 3 4 5; do
        echo '        <dict>'
        echo "            <key>Weekday</key><integer>${weekday}</integer>"
        echo '            <key>Hour</key><integer>9</integer>'
        echo '            <key>Minute</key><integer>25</integer>'
        echo '        </dict>'
    done
    echo '    </array>'
}

interval_schedule() {
    echo '    <key>StartInterval</key>'
    echo "    <integer>$1</integer>"
}

write_plist() {
    local name="$1"
    local subcommand="$2"
    local python_bin="$3"
    local target="${AGENT_DIR}/${LABEL_PREFIX}.${name}.plist"
    mkdir -p "${AGENT_DIR}" "${LOG_DIR}"
    {
        cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL_PREFIX}.${name}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${ORCHESTRATOR}</string>
        <string>${subcommand}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHON_BIN</key>
        <string>${python_bin}</string>
        <key>TZ</key>
        <string>Asia/Shanghai</string>
    </dict>
    <key>RunAtLoad</key>
    <false/>
EOF
        case "${name}" in
            calendar) calendar_schedule ;;
            fundflow) interval_schedule 300 ;;
            quotes) interval_schedule 1800 ;;
        esac
        cat <<EOF
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/launchd-${name}.out.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/launchd-${name}.err.log</string>
</dict>
</plist>
EOF
    } >"${target}"
    echo "${target}"
}

subcommand_for() {
    case "$1" in
        calendar) echo calendar ;;
        fundflow) echo fundflow ;;
        quotes) echo quotes ;;
    esac
}

case "${1:-}" in
    install)
        python_bin="$(detect_python)"
        domain="gui/$(id -u)"
        failures=0
        for name in "${NAMES[@]}"; do
            label="${LABEL_PREFIX}.${name}"
            target="$(write_plist "${name}" "$(subcommand_for "${name}")" "${python_bin}")"
            launchctl bootout "${domain}/${label}" 2>/dev/null || true
            if launchctl bootstrap "${domain}" "${target}" 2>/dev/null; then
                echo "loaded ${label}"
            else
                echo "failed to load ${label}" >&2
                failures=$((failures + 1))
            fi
        done
        if [ "${failures}" -ne 0 ]; then
            cat >&2 <<'MESSAGE'

macOS only accepts launchd bootstrap from your own login session, so an
automation shell usually cannot load these agents. Run the same command from
Terminal.app:

    scripts/install_intraday_launchd.sh install

If that still fails, use the crontab route instead — it needs Full Disk Access
for the terminal in System Settings > Privacy & Security:

    scripts/install_intraday_cron.sh install
MESSAGE
            exit 1
        fi
        ;;
    uninstall)
        domain="gui/$(id -u)"
        for name in "${NAMES[@]}"; do
            label="${LABEL_PREFIX}.${name}"
            launchctl bootout "${domain}/${label}" 2>/dev/null || true
            rm -f "${AGENT_DIR}/${label}.plist"
            echo "removed ${label}"
        done
        ;;
    status)
        domain="gui/$(id -u)"
        for name in "${NAMES[@]}"; do
            label="${LABEL_PREFIX}.${name}"
            if launchctl print "${domain}/${label}" >/dev/null 2>&1; then
                echo "${label}: loaded"
            else
                echo "${label}: not loaded"
            fi
        done
        ;;
    *)
        echo "usage: $(basename "$0") {install|uninstall|status}" >&2
        exit 2
        ;;
esac
