"""Authenticated JSON endpoints for the hundred-day analysis module."""

from core.api.errors import ErrorCode
from core.api.read_endpoints import UnavailableRule, build_read_endpoints
from core.services.market_data import CompleteMarketDataUnavailable
from hundred_day.services.analysis import InsufficientHundredDayHistory
from hundred_day.services.read_path import read_dates, read_hundred_day

results, dates = build_read_endpoints(
    read_result=lambda trade_date=None: read_hundred_day(trade_date),
    read_dates=lambda: read_dates(),
    rules=(
        # 历史不足缺的是"更早的 199 个交易日"，对任何一个已经过去的日期都**不会**
        # 自愈：202 只会让前端进"稍后重试"分支并误导运维。显式指定日期时按规格
        # §5.8 第 6 条返回 404。默认入口（未指定日期）仍可能是"首屏还没准备好"，
        # 保留 202 + INSUFFICIENT_HISTORY，前端据此显示具体原因。
        UnavailableRule(
            InsufficientHundredDayHistory,
            absent_code=ErrorCode.INSUFFICIENT_HISTORY,
            preparing_code=ErrorCode.INSUFFICIENT_HISTORY,
            preparation_state='insufficient_history',
        ),
        UnavailableRule(
            CompleteMarketDataUnavailable,
            absent_message='请求日期没有可用的百日新高新低数据。',
            preparing_message='百日新高新低数据正在准备中，请先运行管理命令。',
        ),
    ),
)
