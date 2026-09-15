from django.contrib import admin

from hundred_day.models import (
    HundredDayBreadth,
    HundredDayIndustrySummary,
    HundredDayStockFlag,
)


@admin.register(HundredDayBreadth)
class HundredDayBreadthAdmin(admin.ModelAdmin):
    """市场宽度：某次发布下每个交易日的有效股票数与新高/新低数。

    业务日期那一行就是页面上的"当日"，其余行是趋势图上的点。
    """

    list_display = (
        'business_date', 'trade_date', 'valid_stock_count', 'new_high_count',
        'new_low_count', 'published_at',
    )
    list_filter = ('business_date',)
    ordering = ('-business_date', 'trade_date')


@admin.register(HundredDayStockFlag)
class HundredDayStockFlagAdmin(admin.ModelAdmin):
    list_display = (
        'business_date', 'stock_code', 'stock_name', 'is_new_high', 'is_new_low',
        'change_percent', 'turnover',
    )
    list_filter = ('business_date', 'is_new_high', 'is_new_low')
    search_fields = ('stock_code', 'stock_name')
    ordering = ('-business_date', 'stock_code')


@admin.register(HundredDayIndustrySummary)
class HundredDayIndustrySummaryAdmin(admin.ModelAdmin):
    """行业级只留成分股数：新高/新低数量由个股标志现算（见 services/read_path.py）。"""

    list_display = ('business_date', 'industry_code', 'industry_name', 'stock_count')
    list_filter = ('business_date',)
    search_fields = ('industry_code', 'industry_name')
    ordering = ('-business_date', 'industry_code')
