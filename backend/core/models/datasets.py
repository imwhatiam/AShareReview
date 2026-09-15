from django.db import models

from core.models.market import Stock


class DailyPrice(models.Model):
    """One stock's forward-adjusted bar for one trading day.

    "Published" and "written" are the same event here: the sync commands validate
    coverage first and then write the whole day inside one transaction, so a day
    either carries its full set of rows or carries none. That is why there is no
    version or run-status row to consult — the rows themselves are the record.
    """

    stock = models.ForeignKey(Stock, on_delete=models.PROTECT)
    trade_date = models.DateField()
    pre_close = models.DecimalField(max_digits=18, decimal_places=4, null=True)
    open_price = models.DecimalField(max_digits=18, decimal_places=4, null=True)
    high_price = models.DecimalField(max_digits=18, decimal_places=4, null=True)
    low_price = models.DecimalField(max_digits=18, decimal_places=4, null=True)
    close_price = models.DecimalField(max_digits=18, decimal_places=4, null=True)
    change_percent = models.DecimalField(max_digits=12, decimal_places=6, null=True)
    volume = models.BigIntegerField(null=True)
    turnover = models.DecimalField(max_digits=24, decimal_places=4, null=True)
    has_valid_trade = models.BooleanField(default=False)
    source_batch_id = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['stock', 'trade_date'],
                name='core_daily_price_stock_trade_date_unique',
            )
        ]
        ordering = ['trade_date', 'stock__stock_code']
