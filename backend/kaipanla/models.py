"""Local data models for the independently deployable Kaipanla module.

One table, one job: a collection appends one row per sector per five-minute
slot, and the API reads those rows back. There is deliberately no run table and
no cross-database bookkeeping — a failed collection leaves nothing behind but a
log line, and the read path answers from whatever rows exist. The reasoning is
in ``services/read_path.py``.

八列只写不读的观测值（``change_pct`` / ``main_buy`` / ``main_sell`` /
``large_order_net_inflow`` / ``volume_ratio`` / ``turnover_amount`` /
``float_market_cap`` / ``total_market_cap``）目前没有任何读方 —— API 只用板块名、
主力净流入与快照时刻。它们是**有意采全**的，不是漏删：这些值不是别的行的函数，
删掉就再也算不出来，只能等下一次采集；对采集型系统来说，把上游给的观测值先落库
备查是常态。逐行成本已量化（约 838 字节/行），真需要瘦身时再连同历史数据一起决定。
"""

from django.db import models
from django.utils import timezone


class KaipanlaSectorFundFlowSnapshot(models.Model):
    """One five-minute-aligned Kaipanla sector fund-flow observation."""

    sector_code = models.CharField(max_length=16, db_index=True, verbose_name='开盘啦板块代码')
    sector_name = models.CharField(max_length=64, verbose_name='开盘啦板块名称')
    trade_date = models.DateField(db_index=True, verbose_name='交易日')
    snapshot_time = models.DateTimeField(db_index=True, verbose_name='快照时间（5分钟对齐）')
    # 从这里到 ``total_market_cap`` 这几列只写不读，留着是有意的决定 —— 理由见
    # 模块 docstring（2026-09-15 结构审查已确认，不是漏删）。
    change_pct = models.DecimalField(
        max_digits=9, decimal_places=3, null=True, blank=True, verbose_name='涨跌幅（%）'
    )
    main_net_inflow = models.DecimalField(
        max_digits=24, decimal_places=2, verbose_name='主力净流入（元）'
    )
    main_buy = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True, verbose_name='主力买入（元）'
    )
    main_sell = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True, verbose_name='主力卖出（元）'
    )
    large_order_net_inflow = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True, verbose_name='大单净额（元）'
    )
    volume_ratio = models.DecimalField(
        max_digits=9, decimal_places=3, null=True, blank=True, verbose_name='量比'
    )
    turnover_amount = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True, verbose_name='成交额（元）'
    )
    float_market_cap = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True, verbose_name='流通市值（元）'
    )
    total_market_cap = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True, verbose_name='总市值（元）'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['sector_code', 'snapshot_time'],
                name='kaipanla_snapshot_sector_time_unique',
            )
        ]
        indexes = [
            models.Index(fields=['sector_code', 'trade_date']),
            models.Index(fields=['trade_date', 'snapshot_time']),
        ]
        ordering = ['snapshot_time', 'sector_code']
        verbose_name = '开盘啦板块资金流快照'
        verbose_name_plural = verbose_name

    def __str__(self):
        local_time = timezone.localtime(self.snapshot_time)
        return f'{self.sector_code} {self.sector_name} @ {local_time:%Y-%m-%d %H:%M}'
