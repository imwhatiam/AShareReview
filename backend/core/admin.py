from django.contrib import admin

from core.models import DailyPrice, IndustrySnapshot, Stock


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_staff

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Stock)
class StockAdmin(ReadOnlyAdmin):
    list_display = ('stock_code', 'stock_name', 'thscode', 'exchange', 'is_active')
    list_filter = ('exchange', 'is_active')
    search_fields = ('stock_code', 'stock_name', 'thscode')


@admin.register(IndustrySnapshot)
class IndustrySnapshotAdmin(ReadOnlyAdmin):
    list_display = ('industry_code', 'industry_name')
    search_fields = ('industry_code', 'industry_name')


@admin.register(DailyPrice)
class DailyPriceAdmin(ReadOnlyAdmin):
    list_display = (
        'stock',
        'trade_date',
        'close_price',
        'change_percent',
        'volume',
        'turnover',
        'has_valid_trade',
        'source_batch_id',
    )
    list_filter = ('has_valid_trade', 'trade_date')
    search_fields = ('stock__stock_code', 'stock__stock_name', 'source_batch_id')
