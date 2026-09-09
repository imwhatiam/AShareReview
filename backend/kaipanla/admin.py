from django.contrib import admin

from kaipanla.models import KaipanlaSectorFundFlowRun, KaipanlaSectorFundFlowSnapshot


@admin.register(KaipanlaSectorFundFlowSnapshot)
class KaipanlaSectorFundFlowSnapshotAdmin(admin.ModelAdmin):
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


@admin.register(KaipanlaSectorFundFlowRun)
class KaipanlaSectorFundFlowRunAdmin(admin.ModelAdmin):
    list_display = (
        'source_batch_id',
        'trade_date',
        'snapshot_time',
        'status',
        'completed_page_count',
        'expected_page_count',
        'actual_record_count',
    )
    list_filter = ('status', 'trade_date')
    search_fields = ('source_batch_id', 'error_summary')
