from django.contrib import admin

from stock_moves.models import StockMoveItem


@admin.register(StockMoveItem)
class StockMoveItemAdmin(admin.ModelAdmin):
    """单表后台：这一天有哪些股票、分别在哪个组、什么名次。

    结果级的数字（六组计数、去重股票数）不在这里列，它们由这些行算出来，
    列出来只是同一个事实的第二份副本。
    """

    list_display = (
        'business_date',
        'group',
        'rank',
        'stock_code',
        'stock_name',
        'change_percent',
        'turnover',
        'published_at',
    )
    list_filter = ('business_date', 'group')
    search_fields = ('stock_code', 'stock_name')
    ordering = ('-business_date', 'group', 'rank')
