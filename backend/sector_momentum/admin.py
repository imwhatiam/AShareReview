from django.contrib import admin

from sector_momentum.models import (
    SectorMomentumRanking,
    SectorMomentumResult,
    SectorMomentumRun,
)


class SectorMomentumRankingInline(admin.TabularInline):
    model = SectorMomentumRanking
    extra = 0
    can_delete = False
    readonly_fields = (
        'metric', 'rank', 'industry_code', 'industry_name', 'stock_count',
        'average_change_percent', 'industry_turnover', 'market_turnover_ratio',
        'score', 'stocks',
    )


@admin.register(SectorMomentumResult)
class SectorMomentumResultAdmin(admin.ModelAdmin):
    list_display = (
        'business_date', 'source_daily_price_version', 'source_industry_version',
        'total_market_turnover', 'unmapped_stock_count',
    )
    list_filter = ('business_date',)
    search_fields = ('source_daily_price_version', 'source_industry_version')
    inlines = (SectorMomentumRankingInline,)


@admin.register(SectorMomentumRun)
class SectorMomentumRunAdmin(admin.ModelAdmin):
    list_display = (
        'source_batch_id', 'business_date', 'status', 'source_daily_price_version',
        'source_industry_version', 'unmapped_stock_count', 'started_at', 'finished_at',
    )
    list_filter = ('status', 'business_date')
    search_fields = (
        'source_batch_id', 'source_daily_price_version', 'source_industry_version',
        'error_summary',
    )
