from django.contrib import admin

from eastmoney.models import EastmoneySectorFundFlowRun, EastmoneySectorFundFlowSnapshot


@admin.register(EastmoneySectorFundFlowSnapshot)
class EastmoneySectorFundFlowSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        'sector_code',
        'sector_name',
        'trade_date',
        'snapshot_time',
        'main_net_inflow',
        'source_batch_id',
    )
    list_filter = ('trade_date',)
    search_fields = ('sector_code', 'sector_name', 'source_batch_id')


@admin.register(EastmoneySectorFundFlowRun)
class EastmoneySectorFundFlowRunAdmin(admin.ModelAdmin):
    list_display = (
        'source_batch_id',
        'trade_date',
        'snapshot_time',
        'status',
        'inflow_status',
        'outflow_status',
        'inflow_record_count',
        'outflow_record_count',
    )
    list_filter = ('status', 'inflow_status', 'outflow_status', 'trade_date')
    search_fields = (
        'source_batch_id',
        'error_summary',
        'inflow_error_summary',
        'outflow_error_summary',
    )
