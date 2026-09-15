from datetime import date

from core.management.base import BaseDataCommand
from core.logging import log_command_progress
from core.services.market_data import get_complete_market_snapshot, resolve_business_date
from sector_momentum.services.analysis import build_sector_momentum_analysis
from sector_momentum.services.industry_source import require_industry_snapshot
from sector_momentum.services.writer import write_sector_momentum_analysis


class Command(BaseDataCommand):
    help = 'Build parent-industry momentum rankings for one trading day.'
    module_id = 'sector_momentum'
    dataset_key = 'sector_momentum'
    failure_message = 'Sector-momentum analysis failed.'

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
        log_command_progress('sector_momentum', action='loading_snapshot', date=business_date)
        snapshot = get_complete_market_snapshot(business_date)
        # 行业映射是排行的分组键：没有它就没有板块，也就没有排行可写。
        require_industry_snapshot()
        log_command_progress('sector_momentum', action='analyzing', date=business_date)
        analysis = build_sector_momentum_analysis(snapshot)
        log_command_progress(
            'sector_momentum',
            action='analyzed',
            date=business_date,
            rankings=sum(len(values) for values in analysis.rankings_by_metric.values()),
        )

        if options['dry_run']:
            return analysis, None, True

        log_command_progress('sector_momentum', action='writing', date=business_date)
        write_result = write_sector_momentum_analysis(
            business_date=business_date,
            analysis=analysis,
        )
        return analysis, write_result, False

    def format_success_message(self, result, options):
        analysis, write_result, dry_run = result
        ranking_count = sum(len(values) for values in analysis.rankings_by_metric.values())
        business_date = self.get_business_date(options).isoformat()
        if dry_run:
            return (
                f'dry-run: would build {ranking_count} sector-momentum rankings '
                f'for {business_date}.'
            )
        return (
            f'built {write_result.record_count} sector-momentum rankings '
            f'for {business_date}.'
        )
