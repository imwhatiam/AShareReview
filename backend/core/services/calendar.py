from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.utils import timezone

from core.models import TradingDay


SHANGHAI_TIME_ZONE = ZoneInfo('Asia/Shanghai')
MARKET_CLOSE_TIME = time(15, 0)


def latest_eligible_trading_day(now: datetime | None = None):
    """Return the latest calendar day eligible for post-close processing."""
    current = now or timezone.now()
    if timezone.is_naive(current):
        current = timezone.make_aware(current, SHANGHAI_TIME_ZONE)
    local_now = current.astimezone(SHANGHAI_TIME_ZONE)
    latest_day = TradingDay.objects.filter(trade_date__lte=local_now.date()).order_by(
        '-trade_date'
    ).first()
    if latest_day is None:
        return None
    if latest_day.trade_date == local_now.date() and local_now.time() < MARKET_CLOSE_TIME:
        latest_day = TradingDay.objects.filter(
            trade_date__lt=local_now.date()
        ).order_by('-trade_date').first()
    return latest_day.trade_date if latest_day is not None else None
