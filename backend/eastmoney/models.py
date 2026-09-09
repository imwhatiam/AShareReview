"""Local data models for the independently deployable Eastmoney module."""

from django.db import models
from django.db.models import Q
from django.utils import timezone


class EastmoneySectorFundFlowSnapshot(models.Model):
    """One Eastmoney sector fund-flow observation from either ranking request."""

    sector_code = models.CharField(max_length=16, db_index=True, verbose_name='东方财富板块代码')
    sector_name = models.CharField(max_length=64, verbose_name='东方财富板块名称')
    trade_date = models.DateField(db_index=True, verbose_name='交易日')
    snapshot_time = models.DateTimeField(db_index=True, verbose_name='快照时间')
    latest_index = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True, verbose_name='板块指数'
    )
    change_pct = models.DecimalField(
        max_digits=9, decimal_places=3, null=True, blank=True, verbose_name='涨跌幅（%）'
    )
    main_net_inflow = models.DecimalField(
        max_digits=24, decimal_places=2, verbose_name='主力净流入（元）'
    )
    main_net_inflow_ratio = models.DecimalField(
        max_digits=9, decimal_places=3, null=True, blank=True, verbose_name='主力净占比（%）'
    )
    super_large_net_inflow = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True, verbose_name='超大单净流入（元）'
    )
    large_net_inflow = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True, verbose_name='大单净流入（元）'
    )
    medium_net_inflow = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True, verbose_name='中单净流入（元）'
    )
    small_net_inflow = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True, verbose_name='小单净流入（元）'
    )
    source_batch_id = models.CharField(max_length=64, db_index=True, verbose_name='采集批次标识')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['sector_code', 'snapshot_time'],
                name='eastmoney_snapshot_sector_time_unique',
            )
        ]
        indexes = [
            models.Index(fields=['sector_code', 'trade_date']),
            models.Index(fields=['trade_date', 'snapshot_time']),
        ]
        ordering = ['snapshot_time', 'sector_code']
        verbose_name = '东方财富板块资金流快照'
        verbose_name_plural = verbose_name

    def __str__(self):
        local_time = timezone.localtime(self.snapshot_time)
        return f'{self.sector_code} {self.sector_name} @ {local_time:%Y-%m-%d %H:%M}'


class EastmoneySectorFundFlowRun(models.Model):
    """Detailed status for the independent inflow and outflow ranking requests."""

    class Status(models.TextChoices):
        RUNNING = 'running', '运行中'
        COMPLETE = 'complete', '完整'
        PARTIAL = 'partial', '部分完成'
        FAILED = 'failed', '失败'

    class DirectionStatus(models.TextChoices):
        PENDING = 'pending', '待执行'
        COMPLETE = 'complete', '成功'
        FAILED = 'failed', '失败'

    source_batch_id = models.CharField(max_length=64, unique=True, verbose_name='采集批次标识')
    trade_date = models.DateField(db_index=True, verbose_name='交易日')
    snapshot_time = models.DateTimeField(db_index=True, verbose_name='快照时间')
    status = models.CharField(max_length=8, choices=Status.choices, verbose_name='运行状态')
    inflow_status = models.CharField(
        max_length=8,
        choices=DirectionStatus.choices,
        default=DirectionStatus.PENDING,
        verbose_name='流入榜状态',
    )
    outflow_status = models.CharField(
        max_length=8,
        choices=DirectionStatus.choices,
        default=DirectionStatus.PENDING,
        verbose_name='流出榜状态',
    )
    inflow_record_count = models.PositiveIntegerField(default=0, verbose_name='流入榜记录数')
    outflow_record_count = models.PositiveIntegerField(default=0, verbose_name='流出榜记录数')
    inflow_error_summary = models.TextField(blank=True, verbose_name='流入榜错误摘要')
    outflow_error_summary = models.TextField(blank=True, verbose_name='流出榜错误摘要')
    started_at = models.DateTimeField(default=timezone.now, verbose_name='开始时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')
    error_summary = models.TextField(blank=True, verbose_name='错误摘要')

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(status='running')
                    | (
                        Q(status='complete')
                        & Q(inflow_status='complete')
                        & Q(outflow_status='complete')
                    )
                    | (
                        Q(status='partial')
                        & (
                            Q(inflow_status='complete', outflow_status='failed')
                            | Q(inflow_status='failed', outflow_status='complete')
                        )
                    )
                    | (
                        Q(status='failed')
                        & Q(inflow_status='failed')
                        & Q(outflow_status='failed')
                    )
                ),
                name='eastmoney_run_status_matches_direction_statuses',
            )
        ]
        indexes = [
            models.Index(fields=['trade_date', 'snapshot_time']),
            models.Index(fields=['status', 'started_at']),
        ]
        ordering = ['-started_at']
        verbose_name = '东方财富板块资金流采集运行'
        verbose_name_plural = verbose_name

    def __str__(self):
        local_time = timezone.localtime(self.snapshot_time)
        return f'{local_time:%Y-%m-%d %H:%M} {self.status}'
