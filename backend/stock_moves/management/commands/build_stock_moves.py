from datetime import date

from core.management.base import BaseDataCommand
from core.logging import log_command_progress
from core.services.market_data import get_complete_market_snapshot, resolve_business_date
from stock_moves.services.analysis import build_stock_move_analysis
from stock_moves.services.industry_source import require_industry_snapshot
from stock_moves.services.writer import write_stock_move_analysis


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
        log_command_progress('stock_moves', action='loading_snapshot', date=business_date)
        snapshot = get_complete_market_snapshot(business_date)
        # 行业映射是第二个输入：结果里每只股票都带 industries，没有它就只能写出
        # 空字段。缺了就失败，不落一份缺字段的结果 —— 读路径会退回旧数据并标 stale。
        require_industry_snapshot()
        log_command_progress('stock_moves', action='analyzing', date=business_date)
        analysis = build_stock_move_analysis(snapshot)
        log_command_progress(
            'stock_moves', action='analyzed', date=business_date, groups=len(analysis.items)
        )

        if options['dry_run']:
            return analysis, None, True

        log_command_progress('stock_moves', action='writing', date=business_date)
        write_result = write_stock_move_analysis(
            business_date=business_date,
            analysis=analysis,
        )
        return analysis, write_result, False

    def format_success_message(self, result, options):
        analysis, write_result, dry_run = result
        business_date = self.get_business_date(options).isoformat()
        if dry_run:
            return (
                f'dry-run: would build {len(analysis.items)} stock-move records '
                f'for {business_date}.'
            )
        return (
            f'built {write_result.record_count} stock-move records '
            f'for {business_date}.'
        )
