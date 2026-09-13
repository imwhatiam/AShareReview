"""Authenticated JSON endpoints for the stock-move business module."""

from core.api.read_endpoints import UnavailableRule, build_read_endpoints
from core.services.market_data import CompleteMarketDataUnavailable
from stock_moves.services.read_path import read_dates, read_stock_moves

results, dates = build_read_endpoints(
    read_result=lambda trade_date=None: read_stock_moves(trade_date),
    read_dates=lambda: read_dates(),
    rules=(
        UnavailableRule(
            CompleteMarketDataUnavailable,
            absent_message='请求日期没有可用的大涨跌幅与大成交量个股数据。',
            preparing_message='大涨跌幅与大成交量个股数据正在准备中，请先运行管理命令。',
        ),
    ),
)
