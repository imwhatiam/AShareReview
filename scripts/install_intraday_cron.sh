#!/usr/bin/env bash
# 安装/查看/卸载盘中采集的 crontab 条目。
#
#   scripts/install_intraday_cron.sh install     # 写入（幂等：先删旧块再写）
#   scripts/install_intraday_cron.sh uninstall   # 移除本项目的条目，保留其他条目
#   scripts/install_intraday_cron.sh show        # 打印当前 crontab
#
# 该 crontab 只做时间调度，真正的交易日判定（节假日、非交易日）由 Django 命令
# 自己完成 —— 所以这里用最朴素的“周一到周五 + 时段”表达式即可。
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORCHESTRATOR="${REPOSITORY_ROOT}/scripts/intraday_orchestrator.sh"
MARKER_BEGIN="# >>> market-review intraday >>>"
MARKER_END="# <<< market-review intraday <<<"

# 定位旧块时按“形状”匹配，而不是按新标记的字面值：本脚本 2026-09-13 改过一次标记
# 串（旧串里带项目目录名）。只认新字面值的话，改名之前安装过的那份 crontab 会被当
# 成用户自己的条目，永久留在那里且 uninstall 再也删不掉 —— 所以这里用正则同时接受
# 新旧两种写法，代价是不必把旧串的字面值再抄回源码里。
MARKER_BEGIN_PATTERN='^# >>> .+ intraday >>>$'
MARKER_END_PATTERN='^# <<< .+ intraday <<<$'

# cron 的 PATH 很窄，且系统自带的 python3 通常没有本项目的依赖，所以把解释器
# 绝对路径内联进每一条命令（而不是用 cron 的环境变量行 —— 那种赋值会污染
# marker 块之后的用户自己的条目）。
detect_python() {
    if [ -x "${REPOSITORY_ROOT}/.venv/bin/python" ]; then
        echo "${REPOSITORY_ROOT}/.venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        command -v python3
    else
        echo "python3"
    fi
}

build_block() {
    local python_bin
    python_bin="$(detect_python)"
    local prefix="cd ${REPOSITORY_ROOT} && PYTHON_BIN=${python_bin} ${ORCHESTRATOR}"
    cat <<EOF
${MARKER_BEGIN}
# 每个交易日 09:25 同步交易日历：盘中命令都要先能查到“今天”。
25 9 * * 1-5 ${prefix} calendar
# 09:30-11:30 / 13:00-15:00 每 5 分钟抓板块资金流快照。
*/5 9-11,13-14 * * 1-5 ${prefix} fundflow
0 15 * * 1-5 ${prefix} fundflow
# 09:30-11:30 / 13:00-15:00 每 30 分钟刷新全市场行情并重建三个盘后模块。
0,30 9-11,13-14 * * 1-5 ${prefix} quotes
0 15 * * 1-5 ${prefix} quotes
${MARKER_END}
EOF
}

current_crontab() {
    crontab -l 2>/dev/null || true
}

strip_block() {
    awk -v begin="${MARKER_BEGIN_PATTERN}" -v end="${MARKER_END_PATTERN}" '
        $0 ~ begin { skip = 1; next }
        $0 ~ end { skip = 0; next }
        !skip { print }
    '
}

case "${1:-}" in
    install)
        {
            current_crontab | strip_block
            build_block
        } | crontab -
        echo "installed intraday crontab entries"
        ;;
    uninstall)
        current_crontab | strip_block | crontab -
        echo "removed intraday crontab entries"
        ;;
    show)
        current_crontab
        ;;
    *)
        echo "usage: $(basename "$0") {install|uninstall|show}" >&2
        exit 2
        ;;
esac
