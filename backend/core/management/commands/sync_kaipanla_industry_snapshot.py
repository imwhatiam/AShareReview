from core.management.base import BaseDataCommand


class Command(BaseDataCommand):
    help = 'Synchronize the Kaipanla industry stock snapshot.'
    dataset_key = 'kaipanla_industry_snapshot'
    failure_message = 'Kaipanla industry snapshot synchronization failed.'

    def add_arguments(self, parser):
        super().add_arguments(parser)

    def run_data_sync(self, options):
        from core.services.sync_industries import sync_kaipanla_industry_snapshot

        return sync_kaipanla_industry_snapshot(dry_run=options['dry_run'])

    def format_success_message(self, result, options):
        mode = 'dry-run: would synchronize' if result.dry_run else 'synchronized'
        return (
            f'{mode} {result.record_count} industry records for {result.business_date}.'
            f' Backfilled {result.backfilled_stock_count} stock assignments from Hithink.'
        )
