from datetime import date

from core.management.base import BaseDataCommand
from core.services.market_data import get_complete_market_snapshot
from stock_moves.services.analysis import build_stock_move_analysis
from stock_moves.services.writer import record_failed_run, write_stock_move_analysis


class Command(BaseDataCommand):
    help = 'Build the four large-move and large-turnover stock groups for one trading day.'
    module_id = 'stock_moves'
    dataset_key = 'stock_moves'
    failure_message = 'Stock-move analysis failed.'

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument('--date', required=True, type=date.fromisoformat)

    def get_business_date(self, options):
        return options['date']

    def run_data_sync(self, options):
        business_date = options['date']
        try:
            snapshot = get_complete_market_snapshot(business_date)
            if snapshot.data_version.business_date != business_date:
                raise ValueError('The public daily-price snapshot date does not match --date.')
            analysis = build_stock_move_analysis(snapshot)
        except Exception as error:
            if not options['dry_run']:
                record_failed_run(business_date=business_date, error=error)
            raise

        if options['dry_run']:
            return analysis, None, True

        write_result = write_stock_move_analysis(
            business_date=business_date,
            source_daily_price_version=snapshot.data_version.version,
            analysis=analysis,
        )
        return analysis, write_result, False

    def format_success_message(self, result, options):
        analysis, write_result, dry_run = result
        if dry_run:
            return (
                f'dry-run: would build {len(analysis.items)} stock-move records '
                f'for {options["date"].isoformat()}.'
            )
        return (
            f'built {write_result.record_count} stock-move records '
            f'for {options["date"].isoformat()}.'
        )
