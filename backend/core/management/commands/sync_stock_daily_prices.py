from datetime import date

from core.management.base import BaseDataCommand


class Command(BaseDataCommand):
    help = 'Synchronize public A-share daily prices for one trading date.'
    dataset_key = 'stock_daily_prices'
    failure_message = 'Daily-price synchronization failed.'

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument('--date', required=True, type=date.fromisoformat)

    def run_data_sync(self, options):
        from core.services.sync_daily_prices import sync_stock_daily_prices

        return sync_stock_daily_prices(
            trade_date=options['date'],
            dry_run=options['dry_run'],
        )

    def format_success_message(self, result, options):
        if result.dry_run:
            return (
                f'dry-run: would synchronize {result.record_count} daily-price records '
                f'for {options["date"].isoformat()}.'
            )
        return (
            f'synchronized {result.record_count} daily-price records '
            f'for {options["date"].isoformat()}.'
        )
