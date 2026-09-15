"""Refresh today's public daily prices from the live whole-market snapshot.

This is the only routine writer of the ``stock_daily_prices`` dataset. It walks
the whole market from one paged snapshot endpoint (about six requests) instead of
issuing one history request per stock, which is why it can run every half hour
without spending the upstream quota that a per-stock history walk costs.

The command has **no ``--date``**: the snapshot endpoint has no date parameter
and always answers with "right now", so a run targeting any other day could only
write today's prices under yesterday's label. The business date is therefore
always today in Asia/Shanghai, and the gate below decides whether that day is
worth asking for.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from core.logging import log_command_progress
from core.management.base import BaseDataCommand
from core.services.calendar import is_trading_day, is_trading_session


_SHANGHAI = ZoneInfo('Asia/Shanghai')


def _now() -> datetime:
    """Return the current Asia/Shanghai wall clock.

    The business date and the session gate must agree on what "now" is, so both
    read the clock here rather than each deriving today on its own.
    """
    return datetime.now(_SHANGHAI)


class Command(BaseDataCommand):
    help = (
        "Refresh every stock's current-day prices from the live whole-market snapshot. "
        'Intended to run every 30 minutes during the trading session, plus once after '
        'the close with --latest.'
    )
    dataset_key = 'stock_daily_prices'
    failure_message = 'Intraday quote refresh failed.'

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            '--latest',
            action='store_true',
            help=(
                'Run outside the trading sessions (midday break, after the close). '
                'Non-trading days are still skipped even with this flag.'
            ),
        )

    def get_business_date(self, options) -> date:
        return _now().date()

    def run_data_sync(self, options):
        from core.services.sync_daily_prices import refresh_intraday_daily_prices

        now = _now()
        trade_date = now.date()
        # 与 fetch_kaipanla_sector_fund_flow 同一套闸门语义：时段外上游只有已收盘的
        # 静态数据，跑一次既拿不到新东西，又白打上游。跳过返回结果而不是抛错（退出码
        # 0、不写失败日志），让 crontab 拿到一次干净的"什么都没发生"。
        #
        # 非交易日连 --latest 也跳过 —— 这一条与资金流命令刻意不同。快照端点没有日期
        # 参数，休市日跑它只会拿到上一交易日的收盘态，写下去等于把那份数据冒充成今天。
        if not is_trading_day(trade_date):
            log_command_progress(
                'stock_daily_prices',
                action='skipped',
                reason='not_a_trading_day',
                trade_date=trade_date,
            )
            return {'skipped': True, 'reason': 'not_a_trading_day', 'trade_date': trade_date}
        if not options['latest'] and not is_trading_session(now):
            log_command_progress(
                'stock_daily_prices',
                action='skipped',
                reason='outside_trading_session',
                trade_date=trade_date,
            )
            return {'skipped': True, 'reason': 'outside_trading_session', 'trade_date': trade_date}

        return refresh_intraday_daily_prices(
            trade_date=trade_date,
            dry_run=options['dry_run'],
        )

    def format_success_message(self, result, options):
        if isinstance(result, dict):
            if result['reason'] == 'not_a_trading_day':
                return f"skipped: {result['trade_date'].isoformat()} is not a trading day."
            return (
                'skipped: outside the A-share trading sessions '
                '(pass --latest to force a run).'
            )
        day = result.trade_date.isoformat()
        if result.dry_run:
            return (
                f'dry-run: would refresh {result.changed_record_count} of '
                f'{result.matched_stock_count} intraday records for {day} '
                f'(coverage {result.coverage_ratio:.4f}).'
            )
        if result.is_up_to_date:
            return f'intraday quotes for {day} are already up to date.'
        return (
            f'refreshed {result.changed_record_count} intraday records '
            f'({result.unchanged_record_count} unchanged) for {day} '
            f'from {result.matched_stock_count} quotes.'
        )
