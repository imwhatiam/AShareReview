from django.contrib import admin

from core.models import (
    DailyPrice,
    DataVersion,
    IndustrySnapshot,
    ModuleRunStatus,
    Stock,
    TradingDay,
)
from core.services.status_summary import safe_error_summary


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


@admin.register(ModuleRunStatus)
class ModuleRunStatusAdmin(ReadOnlyAdmin):
    list_display = (
        'module_id',
        'dataset_key',
        'display_business_date',
        'last_success_at',
        'status',
        'completeness',
        'source_data_version',
        'serving_stale',
        'display_failure_count',
        'safe_error_summary',
    )
    list_filter = ('status', 'completeness', 'serving_stale')
    search_fields = ('module_id', 'dataset_key', 'source_data_version')

    @admin.display(description='业务日期', ordering='business_date')
    def display_business_date(self, obj):
        return obj.business_date

    @admin.display(description='连续失败次数', ordering='consecutive_failure_count')
    def display_failure_count(self, obj):
        return obj.consecutive_failure_count

    @admin.display(description='安全错误摘要')
    def safe_error_summary(self, obj):
        return safe_error_summary(obj.error_summary)


@admin.register(DataVersion)
class DataVersionAdmin(ReadOnlyAdmin):
    list_display = (
        'dataset_key',
        'version',
        'business_date',
        'status',
        'expected_record_count',
        'actual_record_count',
        'missing_record_count',
        'started_at',
        'finished_at',
        'last_success_at',
        'safe_error_summary',
    )
    list_filter = ('status',)
    search_fields = ('dataset_key', 'version')

    @admin.display(description='安全错误摘要')
    def safe_error_summary(self, obj):
        return safe_error_summary(obj.error_summary)


@admin.register(Stock)
class StockAdmin(ReadOnlyAdmin):
    list_display = ('stock_code', 'stock_name', 'thscode', 'exchange', 'is_active')
    list_filter = ('exchange', 'is_active')
    search_fields = ('stock_code', 'stock_name', 'thscode')


@admin.register(TradingDay)
class TradingDayAdmin(ReadOnlyAdmin):
    list_display = ('trade_date',)


@admin.register(IndustrySnapshot)
class IndustrySnapshotAdmin(ReadOnlyAdmin):
    list_display = ('industry_code', 'industry_name', 'industry_level')
    list_filter = ('industry_level',)
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
        'source_data_version',
    )
    list_filter = ('has_valid_trade', 'trade_date')
    search_fields = ('stock__stock_code', 'stock__stock_name', 'source_data_version')
