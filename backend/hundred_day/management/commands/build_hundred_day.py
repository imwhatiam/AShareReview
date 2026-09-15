from datetime import date

from core.management.base import BaseDataCommand
from core.logging import log_command_progress
from core.services.market_data import resolve_business_date
from hundred_day.services.analysis import build_hundred_day_analysis
from hundred_day.services.industry_source import require_industry_snapshot
from hundred_day.services.source_data import load_hundred_day_source_data
from hundred_day.services.writer import write_hundred_day_analysis


class Command(BaseDataCommand):
    help = 'Build hundred-day high/low results for one trading day from local public data.'
    module_id = 'hundred_day'
    dataset_key = 'hundred_day'
    failure_message = 'Hundred-day analysis failed.'

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            '--date',
            type=date.fromisoformat,
            default=None,
            help=(
                'Trading day to build; defaults to the newest day that has stored '
                'public prices — the same anchor the pages read.'
            ),
        )

    def get_business_date(self, options):
        return resolve_business_date(options['date'])

    def run_data_sync(self, options):
        business_date = self.get_business_date(options)
        log_command_progress('hundred_day', action='loading_source', date=business_date)
        source = load_hundred_day_source_data(business_date)
        # 行业归属决定每只股票所属板块，也决定板块汇总怎么分组。
        require_industry_snapshot()
        log_command_progress('hundred_day', action='analyzing', date=business_date)
        analysis = build_hundred_day_analysis(source)
        log_command_progress(
            'hundred_day',
            action='analyzed',
            date=business_date,
            stocks=len(analysis.stock_flags),
        )

        if options['dry_run']:
            return analysis, None, True
        log_command_progress('hundred_day', action='writing', date=business_date)
        return analysis, write_hundred_day_analysis(analysis=analysis), False

    def format_success_message(self, result, options):
        analysis, write_result, dry_run = result
        business_date = self.get_business_date(options).isoformat()
        if dry_run:
            return (
                'dry-run: would build '
                f'{len(analysis.stock_flags)} hundred-day stock flags for '
                f'{business_date}.'
            )
        return (
            f'built {write_result.record_count} hundred-day stock flags for '
            f'{business_date}.'
        )
