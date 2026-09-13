from datetime import date

from core.management.base import BaseDataCommand
from core.logging import log_command_progress
from hundred_day.services.analysis import build_hundred_day_analysis
from hundred_day.services.source_data import load_hundred_day_source_data
from hundred_day.services.source_versions import get_complete_industry_snapshot_version
from hundred_day.services.writer import record_failed_run, write_hundred_day_analysis


class Command(BaseDataCommand):
    help = 'Build hundred-day high/low results for one trading day from local public data.'
    module_id = 'hundred_day'
    dataset_key = 'hundred_day'
    failure_message = 'Hundred-day analysis failed.'

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument('--date', required=True, type=date.fromisoformat)

    def get_business_date(self, options):
        return options['date']

    def run_data_sync(self, options):
        business_date = options['date']
        source_daily_price_version = ''
        source_industry_version = ''
        try:
            log_command_progress('hundred_day', action='loading_source', date=business_date)
            source = load_hundred_day_source_data(business_date)
            source_daily_price_version = source.data_version.version
            source_industry_version = get_complete_industry_snapshot_version()
            log_command_progress(
                'hundred_day', action='analyzing', date=business_date, source=source_daily_price_version
            )
            analysis = build_hundred_day_analysis(
                source, source_industry_version=source_industry_version
            )
            log_command_progress(
                'hundred_day',
                action='analyzed',
                date=business_date,
                stocks=len(analysis.stock_flags),
            )
        except Exception as error:
            if not options['dry_run']:
                record_failed_run(
                    business_date=business_date,
                    error=error,
                    source_daily_price_version=source_daily_price_version,
                    source_industry_version=source_industry_version,
                )
            raise

        if options['dry_run']:
            return analysis, None, True
        log_command_progress('hundred_day', action='writing', date=business_date)
        return analysis, write_hundred_day_analysis(analysis=analysis), False

    def format_success_message(self, result, options):
        analysis, write_result, dry_run = result
        if dry_run:
            return (
                'dry-run: would build '
                f'{len(analysis.stock_flags)} hundred-day stock flags for '
                f'{options["date"].isoformat()}.'
            )
        return (
            f'built {write_result.record_count} hundred-day stock flags for '
            f'{options["date"].isoformat()}.'
        )
