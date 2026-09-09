from django.contrib import admin

from hundred_day.models import (
    HundredDayIndustrySummary,
    HundredDayResult,
    HundredDayRun,
    HundredDayStockFlag,
    HundredDayTrend,
)


class HundredDayStockFlagInline(admin.TabularInline):
    model = HundredDayStockFlag
    extra = 0
    can_delete = False
    readonly_fields = (
        'stock_code', 'stock_name', 'parent_industries', 'is_new_high', 'is_new_low',
    )


class HundredDayIndustrySummaryInline(admin.TabularInline):
    model = HundredDayIndustrySummary
    extra = 0
    can_delete = False
    readonly_fields = (
        'industry_code', 'industry_name', 'stock_count', 'new_high_count', 'new_low_count',
        'new_high_stocks', 'new_low_stocks',
    )


@admin.register(HundredDayResult)
class HundredDayResultAdmin(admin.ModelAdmin):
    list_display = (
        'business_date', 'source_daily_price_version', 'source_industry_version',
        'valid_stock_count', 'new_high_count', 'new_low_count',
    )
    list_filter = ('business_date',)
    search_fields = ('source_daily_price_version', 'source_industry_version')
    inlines = (HundredDayStockFlagInline, HundredDayIndustrySummaryInline)


@admin.register(HundredDayTrend)
class HundredDayTrendAdmin(admin.ModelAdmin):
    list_display = (
        'result', 'trade_date', 'valid_stock_count', 'new_high_count', 'new_low_count',
        'new_high_ratio', 'new_low_ratio',
    )
    list_filter = ('trade_date',)


@admin.register(HundredDayRun)
class HundredDayRunAdmin(admin.ModelAdmin):
    list_display = (
        'source_batch_id', 'business_date', 'status', 'source_daily_price_version',
        'source_industry_version', 'valid_stock_count', 'started_at', 'finished_at',
    )
    list_filter = ('status', 'business_date')
    search_fields = (
        'source_batch_id', 'source_daily_price_version', 'source_industry_version',
        'error_summary',
    )
