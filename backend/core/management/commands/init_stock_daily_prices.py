from core.management.base import BaseDataCommand


class Command(BaseDataCommand):
    help = 'Initialize one year of public A-share daily prices exactly once.'
    dataset_key = 'stock_daily_prices'
    failure_message = 'Initial daily-price import failed.'

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument('--years', type=int, default=1)

    def run_data_sync(self, options):
        from core.services.sync_daily_prices import initialize_stock_daily_prices

        return initialize_stock_daily_prices(
            years=options['years'],
            dry_run=options['dry_run'],
        )

    def format_success_message(self, result, options):
        if result.dry_run:
            return (
                f'dry-run: would initialize {result.trading_day_count} trading days '
                f'and {result.record_count} daily-price records.'
            )
        return (
            f'initialized {result.trading_day_count} trading days and '
            f'{result.record_count} daily-price records.'
        )
