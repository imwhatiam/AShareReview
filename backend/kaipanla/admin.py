from django.contrib import admin

from kaipanla.models import KaipanlaSectorFundFlowSnapshot


@admin.register(KaipanlaSectorFundFlowSnapshot)
class KaipanlaSectorFundFlowSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        'sector_code',
        'sector_name',
        'trade_date',
        'snapshot_time',
        'main_net_inflow',
        'created_at',
    )
    list_filter = ('trade_date',)
    search_fields = ('sector_code', 'sector_name')
