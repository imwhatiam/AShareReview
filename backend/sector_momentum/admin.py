from django.contrib import admin

from sector_momentum.models import SectorMomentumRanking


@admin.register(SectorMomentumRanking)
class SectorMomentumRankingAdmin(admin.ModelAdmin):
    """单表后台：这一天每个口径下有哪些行业、各自入选了哪些股票。

    名次与评分不在列表里列，它们由 ``stocks`` 现算（见
    ``services/read_path.py``），列出来只是同一个事实的第二份副本。
    """

    list_display = (
        'business_date',
        'metric',
        'industry_code',
        'industry_name',
        'total_market_turnover',
        'unmapped_stock_count',
        'published_at',
    )
    list_filter = ('business_date', 'metric')
    search_fields = ('industry_code', 'industry_name')
    ordering = ('-business_date', 'metric', 'industry_code')
