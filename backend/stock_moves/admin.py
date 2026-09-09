from django.contrib import admin

from stock_moves.models import StockMoveItem, StockMoveResult, StockMoveRun


class StockMoveItemInline(admin.TabularInline):
    model = StockMoveItem
    extra = 0
    readonly_fields = (
        'group',
        'rank',
        'stock_code',
        'stock_name',
        'parent_industries',
        'change_percent',
        'turnover',
    )
    can_delete = False


@admin.register(StockMoveResult)
class StockMoveResultAdmin(admin.ModelAdmin):
    list_display = (
        'business_date',
        'source_daily_price_version',
        'sse_rise_count',
        'sse_fall_count',
        'szse_rise_count',
        'szse_fall_count',
        'distinct_stock_count',
        'warnings',
    )
    list_filter = ('business_date',)
    search_fields = ('source_daily_price_version', 'source_industry_version')
    inlines = (StockMoveItemInline,)


@admin.register(StockMoveRun)
class StockMoveRunAdmin(admin.ModelAdmin):
    list_display = (
        'source_batch_id',
        'business_date',
        'status',
        'source_daily_price_version',
        'total_candidate_count',
        'started_at',
        'finished_at',
    )
    list_filter = ('status', 'business_date')
    search_fields = ('source_batch_id', 'source_daily_price_version', 'error_summary')
