from core.management.base import BaseDataCommand


class Command(BaseDataCommand):
    help = 'Synchronize the public A-share stock master from Hithink REST.'
    dataset_key = 'stock_master'
    failure_message = 'Stock master synchronization failed.'

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument('--limit', type=int, default=1000)

    def run_data_sync(self, options):
        from core.services.sync_reference import sync_stock_master

        return sync_stock_master(
            page_size=options['limit'],
            dry_run=options['dry_run'],
        )

    def format_success_message(self, result, options):
        mode = 'dry-run: would synchronize' if result.dry_run else 'synchronized'
        return f'{mode} {result.record_count} stock records.'
