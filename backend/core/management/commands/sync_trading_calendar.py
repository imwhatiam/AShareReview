from core.management.base import BaseDataCommand


class Command(BaseDataCommand):
    help = 'Synchronize the recent one-year A-share trading calendar from Hithink REST.'
    dataset_key = 'trading_calendar'
    failure_message = 'Trading-calendar synchronization failed.'

    def add_arguments(self, parser):
        super().add_arguments(parser)

    def run_data_sync(self, options):
        from core.services.sync_reference import sync_trading_calendar

        return sync_trading_calendar(dry_run=options['dry_run'])

    def format_success_message(self, result, options):
        mode = 'dry-run: would synchronize' if result.dry_run else 'synchronized'
        return f'{mode} {result.record_count} trading days.'
