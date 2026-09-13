from core.management.base import BaseDataCommand


class Command(BaseDataCommand):
    help = 'Import one year of public A-share daily prices, revising existing rows.'
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
            if result.is_up_to_date:
                return (
                    f'dry-run: {result.record_count} daily-price records for '
                    f'{result.trading_day_count} trading days already match upstream; '
                    f'nothing to update.'
                )
            if result.is_initial_import:
                return (
                    f'dry-run: would initialize {result.trading_day_count} trading days '
                    f'and {result.record_count} daily-price records.'
                )
            return (
                f'dry-run: would update {result.changed_record_count} of '
                f'{result.record_count} daily-price records across '
                f'{result.updated_trading_day_count} trading days.'
            )
        if result.is_initial_import:
            return (
                f'initialized {result.trading_day_count} trading days and '
                f'{result.record_count} daily-price records.'
            )
        if result.is_up_to_date:
            return (
                f'no changes: {result.record_count} daily-price records for '
                f'{result.trading_day_count} trading days already match upstream.'
            )
        return (
            f'updated {result.changed_record_count} of {result.record_count} daily-price '
            f'records across {result.updated_trading_day_count} trading days '
            f'({result.unchanged_record_count} unchanged).'
        )
