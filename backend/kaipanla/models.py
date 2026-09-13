"""Local data models for the independently deployable Kaipanla module."""

from django.db import models
from django.utils import timezone


class KaipanlaSectorFundFlowSnapshot(models.Model):
    """One five-minute-aligned Kaipanla sector fund-flow observation."""

    sector_code = models.CharField(max_length=16, db_index=True, verbose_name='开盘啦板块代码')
    sector_name = models.CharField(max_length=64, verbose_name='开盘啦板块名称')
    trade_date = models.DateField(db_index=True, verbose_name='交易日')
    snapshot_time = models.DateTimeField(db_index=True, verbose_name='快照时间（5分钟对齐）')
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
    # 写入这份快照的 DataVersion。没有它，"行已经落库、版本还没标 complete"的那个
    # 崩溃窗口会把新数据打上**旧**版本号返回（并按旧版本键写缓存，之后一直命中假
    # 缓存）。读路径按"已发布版本集合"过滤本列，未发布的行就永远不可见。
    source_data_version = models.CharField(
        max_length=64, db_index=True, blank=True, default='', verbose_name='数据版本'
    )
    source_batch_id = models.CharField(max_length=64, db_index=True, verbose_name='采集批次标识')
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


class KaipanlaSectorFundFlowRun(models.Model):
    """Detailed local record of one paginated Kaipanla snapshot collection."""

    class Status(models.TextChoices):
        RUNNING = 'running', '运行中'
        COMPLETE = 'complete', '完整'
        FAILED = 'failed', '失败'

    source_batch_id = models.CharField(max_length=64, unique=True, verbose_name='采集批次标识')
    trade_date = models.DateField(db_index=True, verbose_name='交易日')
    snapshot_time = models.DateTimeField(db_index=True, verbose_name='快照时间（5分钟对齐）')
    status = models.CharField(max_length=8, choices=Status.choices, verbose_name='运行状态')
    expected_page_count = models.PositiveIntegerField(default=0, verbose_name='预计页数')
    completed_page_count = models.PositiveIntegerField(default=0, verbose_name='完成页数')
    failed_page_offsets = models.JSONField(default=list, verbose_name='失败页偏移量')
    expected_record_count = models.PositiveIntegerField(default=0, verbose_name='预计记录数')
    actual_record_count = models.PositiveIntegerField(default=0, verbose_name='实际记录数')
    missing_record_count = models.PositiveIntegerField(default=0, verbose_name='缺失记录数')
    started_at = models.DateTimeField(default=timezone.now, verbose_name='开始时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')
    error_summary = models.TextField(blank=True, verbose_name='错误摘要')

    class Meta:
        indexes = [
            models.Index(fields=['trade_date', 'snapshot_time']),
            models.Index(fields=['status', 'started_at']),
        ]
        ordering = ['-started_at']
        verbose_name = '开盘啦板块资金流采集运行'
        verbose_name_plural = verbose_name

    def __str__(self):
        local_time = timezone.localtime(self.snapshot_time)
        return f'{local_time:%Y-%m-%d %H:%M} {self.status}'
