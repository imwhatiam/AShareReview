from datetime import date, datetime
from zoneinfo import ZoneInfo

from core.management.base import BaseDataCommand


_SHANGHAI = ZoneInfo('Asia/Shanghai')


def _today() -> date:
    return datetime.now(_SHANGHAI).date()


class Command(BaseDataCommand):
    help = (
        "Refresh every stock's current-day prices from the live whole-market snapshot. "
        'Intended to run every 30 minutes during the trading session.'
    )
    dataset_key = 'stock_daily_prices'
    failure_message = 'Intraday quote refresh failed.'

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            '--date',
            type=date.fromisoformat,
            default=None,
            help='Trading day to refresh; defaults to today in Asia/Shanghai.',
        )

    def get_business_date(self, options):
        return options['date'] or _today()

    def run_data_sync(self, options):
        from core.services.sync_daily_prices import refresh_intraday_daily_prices

        return refresh_intraday_daily_prices(
            trade_date=self.get_business_date(options),
            dry_run=options['dry_run'],
        )

    def format_success_message(self, result, options):
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
