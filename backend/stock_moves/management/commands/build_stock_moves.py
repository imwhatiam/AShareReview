from datetime import date

from core.management.base import BaseDataCommand
from core.logging import log_command_progress
from core.services.market_data import get_complete_market_snapshot
from stock_moves.services.analysis import build_stock_move_analysis
from stock_moves.services.source_versions import get_complete_industry_snapshot_version
from stock_moves.services.writer import record_failed_run, write_stock_move_analysis


class Command(BaseDataCommand):
    help = (
        'Build the four SSE/SZSE large-move groups plus the Beijing Stock Exchange group '
        'for one trading day.'
    )
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
            log_command_progress('stock_moves', action='loading_snapshot', date=business_date)
            snapshot = get_complete_market_snapshot(business_date)
            if snapshot.data_version.business_date != business_date:
                raise ValueError('The public daily-price snapshot date does not match --date.')
            # 行业映射是第二个输入：结果里每只股票都带 industries，命令也要按
            # 同一个版本号落库，否则读路径无法判断它是否还跟得上。
            industry_version = get_complete_industry_snapshot_version()
            log_command_progress('stock_moves', action='analyzing', date=business_date)
            analysis = build_stock_move_analysis(snapshot)
            log_command_progress(
                'stock_moves', action='analyzed', date=business_date, groups=len(analysis.items)
            )
        except Exception as error:
            if not options['dry_run']:
                record_failed_run(business_date=business_date, error=error)
            raise

        if options['dry_run']:
            return analysis, None, True

        log_command_progress('stock_moves', action='writing', date=business_date)
        write_result = write_stock_move_analysis(
            business_date=business_date,
            source_daily_price_version=snapshot.data_version.version,
            source_industry_version=industry_version,
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
