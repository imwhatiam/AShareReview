from django.db import models
from django.utils import timezone

from core.models.market import Stock


class DailyPrice(models.Model):
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
    source_data_version = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['stock', 'trade_date'],
                name='core_daily_price_stock_trade_date_unique',
            )
        ]
        ordering = ['trade_date', 'stock__stock_code']


class DataVersion(models.Model):
    class Status(models.TextChoices):
        RUNNING = 'running', '运行中'
        COMPLETE = 'complete', '完整'
        PARTIAL = 'partial', '部分完成'
        FAILED = 'failed', '失败'

    dataset_key = models.CharField(max_length=64)
    version = models.CharField(max_length=64, unique=True)
    business_date = models.DateField(null=True, blank=True)
    coverage_start_date = models.DateField(null=True, blank=True)
    coverage_end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices)
    expected_record_count = models.PositiveIntegerField(default=0)
    actual_record_count = models.PositiveIntegerField(default=0)
    missing_record_count = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    error_summary = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']


class ModuleRunStatus(models.Model):
    class Status(models.TextChoices):
        IDLE = 'idle', '空闲'
        RUNNING = 'running', '运行中'
        SUCCESS = 'success', '成功'
        FAILED = 'failed', '失败'

    module_id = models.CharField(max_length=64)
    dataset_key = models.CharField(max_length=64)
    status = models.CharField(max_length=8, choices=Status.choices)
    completeness = models.CharField(
        max_length=8, choices=DataVersion.Status.choices, default=DataVersion.Status.RUNNING
    )
    business_date = models.DateField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    source_data_version = models.CharField(max_length=64, blank=True)
    serving_stale = models.BooleanField(default=False)
    consecutive_failure_count = models.PositiveIntegerField(default=0)
    error_summary = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['module_id', 'dataset_key'],
                name='core_module_run_status_module_dataset_unique',
            )
        ]
        ordering = ['module_id', 'dataset_key']
