"""Bounded local public-data loader for hundred-day analysis."""

from datetime import date

from core.models import DailyPrice, DataVersion, TradingDay
from core.services.contracts import MarketDataVersion
from core.services.market_data import (
    STOCK_DAILY_PRICES_DATASET,
    CompleteMarketDataUnavailable,
    get_complete_market_snapshot,
)
from hundred_day.services.analysis import (
    HistoricalCloseData,
    MAX_INPUT_TRADING_DAY_POSITIONS,
    TargetDayQuote,
)


def _recent_trading_days(business_date: date) -> tuple[date, ...]:
    dates = list(
        TradingDay.objects.filter(trade_date__lte=business_date)
        .order_by('-trade_date')
        .values_list('trade_date', flat=True)[:MAX_INPUT_TRADING_DAY_POSITIONS]
    )
    return tuple(reversed(dates))


def load_hundred_day_source_data(business_date: date) -> HistoricalCloseData:
    """Load no more than 199 local calendar positions and their recorded closes."""
    target_snapshot = get_complete_market_snapshot(business_date)
    trading_days = _recent_trading_days(business_date)
    if not trading_days or trading_days[-1] != business_date:
        raise CompleteMarketDataUnavailable(
            f'No local trading-calendar position exists for {business_date.isoformat()}.'
        )

    # 每个交易日的"当前版本"。同一天可能有多次发布，取"最近一次成功"的那个，
    # 与 get_complete_market_snapshot 的口径一致（否则目标日的快照和这里的窗口
    # 可能来自两个版本）。
    versions_by_date = dict(
        DataVersion.objects.filter(
            dataset_key=STOCK_DAILY_PRICES_DATASET,
            status=DataVersion.Status.COMPLETE,
            business_date__in=trading_days,
        )
        .order_by('business_date', 'last_success_at', 'started_at')
        .values_list('business_date', 'version')
    )
    missing_dates = [day for day in trading_days if day not in versions_by_date]
    if missing_dates:
        raise CompleteMarketDataUnavailable(
            'No complete local daily-price version exists for trading-day position '
            f'{min(missing_dates).isoformat()}.'
        )

    # 一天 5571 行 × 199 个交易日约 110 万行：逐对象构造 ORM 实例要 15 秒左右，
    # 批量取值只要不到 2 秒。这是请求内按需生成能接受的前提。
    #
    # 必须按 source_data_version 过滤：一次重跑会把当天全部行改挂新版本，而任何
    # 一次"改归属"没跑完全，就会留下若干仍挂旧版本的行 —— 它们的收盘价属于旧数据，
    # 混进 199 日滑窗会静默污染极值，而产物版本号看不出来。
    #
    # 这里用「日期集合 + 版本字符串集合」而不是逐日 OR 出 199 组 (日期, 版本)：
    # 这个查询在请求内全表扫约 110 万行，`__in` 是每行两次集合判等，199 个谓词的
    # OR 链不是。它仍然是精确的 —— 一个版本字符串只由一次发布创建、也只被写到那次
    # 发布的业务日期上，所以"版本字符串在集合里"就等价于"它就是这一天的当前版本"。
    close_prices_by_stock: dict[str, dict] = {}
    stock_names_by_code: dict[str, str] = {}
    target_day_quotes: dict[str, TargetDayQuote] = {}
    rows = DailyPrice.objects.filter(
        trade_date__in=trading_days,
        source_data_version__in=set(versions_by_date.values()),
    ).values_list(
        'stock__stock_code',
        'stock__stock_name',
        'trade_date',
        'close_price',
        'has_valid_trade',
        'change_percent',
        'turnover',
    )
    for (
        stock_code,
        stock_name,
        trade_date,
        close_price,
        has_valid_trade,
        change_percent,
        turnover,
    ) in rows:
        stock_names_by_code[stock_code] = stock_name
        close_prices_by_stock.setdefault(stock_code, {})[trade_date] = (
            close_price if has_valid_trade else None
        )
        if trade_date == business_date:
            target_day_quotes[stock_code] = TargetDayQuote(
                change_percent=change_percent if has_valid_trade else None,
                turnover=turnover if has_valid_trade else None,
            )

    return HistoricalCloseData(
        data_version=MarketDataVersion(
            version=target_snapshot.data_version.version,
            business_date=business_date,
        ),
        trading_days=trading_days,
        close_prices_by_stock=close_prices_by_stock,
        stock_names_by_code=stock_names_by_code,
        industries=target_snapshot.industries,
        target_day_quotes=target_day_quotes,
    )
