"""Authenticated JSON endpoints for the sector-momentum module."""

from core.api.read_endpoints import UnavailableRule, build_read_endpoints
from core.services.market_data import CompleteMarketDataUnavailable
from sector_momentum.services.read_path import read_dates, read_sector_momentum

results, dates = build_read_endpoints(
    read_result=lambda trade_date=None: read_sector_momentum(trade_date),
    read_dates=lambda: read_dates(),
    rules=(
        UnavailableRule(
            CompleteMarketDataUnavailable,
            absent_message='请求日期没有可用的板块动量数据。',
            preparing_message='板块动量数据正在准备中，请先运行管理命令。',
        ),
    ),
)
