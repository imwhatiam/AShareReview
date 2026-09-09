from datetime import date

from core.management.base import BaseDataCommand
from core.services.market_data import get_complete_market_snapshot
from sector_momentum.services.analysis import build_sector_momentum_analysis
from sector_momentum.services.source_versions import get_complete_industry_snapshot_version
from sector_momentum.services.writer import record_failed_run, write_sector_momentum_analysis


class Command(BaseDataCommand):
    help = 'Build parent-industry momentum rankings for one trading day.'
    module_id = 'sector_momentum'
    dataset_key = 'sector_momentum'
    failure_message = 'Sector-momentum analysis failed.'

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
            snapshot = get_complete_market_snapshot(business_date)
            source_daily_price_version = snapshot.data_version.version
            if snapshot.data_version.business_date != business_date:
                raise ValueError('The public daily-price snapshot date does not match --date.')
            source_industry_version = get_complete_industry_snapshot_version()
            analysis = build_sector_momentum_analysis(snapshot, source_industry_version)
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

        write_result = write_sector_momentum_analysis(
            business_date=business_date,
            analysis=analysis,
        )
        return analysis, write_result, False

    def format_success_message(self, result, options):
        analysis, write_result, dry_run = result
        ranking_count = sum(len(values) for values in analysis.rankings_by_metric.values())
        if dry_run:
            return (
                f'dry-run: would build {ranking_count} sector-momentum rankings '
                f'for {options["date"].isoformat()}.'
            )
        return (
            f'built {write_result.record_count} sector-momentum rankings '
            f'for {options["date"].isoformat()}.'
        )
