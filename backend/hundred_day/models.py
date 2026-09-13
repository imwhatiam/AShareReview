"""Persistent derived data for the 百日新高新低占比 module."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class HundredDayResult(models.Model):
    """Published hundred-day high/low analysis for one source-version pair."""

    business_date = models.DateField(db_index=True, verbose_name='业务日期')
    source_daily_price_version = models.CharField(max_length=64, verbose_name='公共日行情版本')
    source_industry_version = models.CharField(max_length=64, verbose_name='行业映射版本')
    valid_stock_count = models.PositiveIntegerField(default=0, verbose_name='有效股票数')
    new_high_count = models.PositiveIntegerField(default=0, verbose_name='新高数量')
    new_low_count = models.PositiveIntegerField(default=0, verbose_name='新低数量')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['business_date', 'source_daily_price_version', 'source_industry_version'],
                name='hundred_day_result_source_version_unique',
            ),
        ]
        indexes = [models.Index(fields=['business_date', 'created_at'])]
        ordering = ['-business_date', '-created_at']
        verbose_name = '百日新高新低结果'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.business_date} ({self.source_daily_price_version})'


class HundredDayStockFlag(models.Model):
    """A stock-level flag, preserving parent-industry membership at publication time."""

    result = models.ForeignKey(
        HundredDayResult,
        on_delete=models.CASCADE,
        related_name='stock_flags',
        verbose_name='分析结果',
    )
    stock_code = models.CharField(max_length=6, verbose_name='股票代码')
    stock_name = models.CharField(max_length=64, verbose_name='股票名称')
    industries = models.JSONField(default=list, verbose_name='所属行业快照')
    is_new_high = models.BooleanField(default=False, verbose_name='是否新高')
    is_new_low = models.BooleanField(default=False, verbose_name='是否新低')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['result', 'stock_code'],
                name='hundred_day_result_stock_unique',
            ),
        ]
        ordering = ['stock_code']
        verbose_name = '百日新高新低股票标志'
        verbose_name_plural = verbose_name

    def clean(self):
        super().clean()
        if not self.is_new_high and not self.is_new_low:
            raise ValidationError('股票标志至少需要是新高或新低之一。')

    def __str__(self):
        return self.stock_code


class HundredDayIndustrySummary(models.Model):
    """Parent-industry aggregates and display-ready stock details."""

    result = models.ForeignKey(
        HundredDayResult,
        on_delete=models.CASCADE,
        related_name='industry_summaries',
        verbose_name='分析结果',
    )
    industry_code = models.CharField(max_length=32, verbose_name='行业代码')
    industry_name = models.CharField(max_length=64, verbose_name='行业名称')
    stock_count = models.PositiveIntegerField(default=0, verbose_name='行业股票数')
    new_high_count = models.PositiveIntegerField(default=0, verbose_name='新高数量')
    new_low_count = models.PositiveIntegerField(default=0, verbose_name='新低数量')
    new_high_stocks = models.JSONField(default=list, verbose_name='新高股票明细')
    new_low_stocks = models.JSONField(default=list, verbose_name='新低股票明细')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['result', 'industry_code'],
                name='hundred_day_result_industry_unique',
            ),
        ]
        ordering = ['industry_code']
        verbose_name = '百日新高新低板块汇总'
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.industry_name


class HundredDayTrend(models.Model):
    """One structured daily point in a result's most-recent 100-day trend."""

    result = models.ForeignKey(
        HundredDayResult,
        on_delete=models.CASCADE,
        related_name='trend_points',
        verbose_name='分析结果',
    )
    trade_date = models.DateField(verbose_name='交易日期')
    valid_stock_count = models.PositiveIntegerField(default=0, verbose_name='有效股票数')
    new_high_count = models.PositiveIntegerField(default=0, verbose_name='新高数量')
    new_low_count = models.PositiveIntegerField(default=0, verbose_name='新低数量')
    new_high_ratio = models.DecimalField(
        max_digits=12, decimal_places=8, null=True, blank=True, verbose_name='新高占比'
    )
    new_low_ratio = models.DecimalField(
        max_digits=12, decimal_places=8, null=True, blank=True, verbose_name='新低占比'
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['result', 'trade_date'],
                name='hundred_day_result_trend_date_unique',
            ),
        ]
        ordering = ['trade_date']
        verbose_name = '百日新高新低趋势点'
        verbose_name_plural = verbose_name

    def __str__(self):
        return str(self.trade_date)


class HundredDayRun(models.Model):
    """An independent execution record for one analysis build attempt."""

    class Status(models.TextChoices):
        RUNNING = 'running', '运行中'
        SUCCESS = 'success', '成功'
        FAILED = 'failed', '失败'

    source_batch_id = models.CharField(max_length=64, unique=True, verbose_name='运行批次标识')
    business_date = models.DateField(db_index=True, verbose_name='业务日期')
    status = models.CharField(max_length=8, choices=Status.choices, verbose_name='运行状态')
    source_daily_price_version = models.CharField(
        max_length=64, blank=True, verbose_name='公共日行情版本'
    )
    source_industry_version = models.CharField(max_length=64, blank=True, verbose_name='行业映射版本')
    published_result_id = models.PositiveBigIntegerField(
        null=True, blank=True, verbose_name='已发布结果标识'
    )
    valid_stock_count = models.PositiveIntegerField(default=0, verbose_name='有效股票数')
    started_at = models.DateTimeField(default=timezone.now, verbose_name='开始时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')
    error_summary = models.TextField(blank=True, verbose_name='错误摘要')

    class Meta:
        indexes = [
            models.Index(fields=['business_date', 'started_at']),
            models.Index(fields=['status', 'started_at']),
        ]
        ordering = ['-started_at']
        verbose_name = '百日新高新低运行记录'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.business_date} {self.status} ({self.source_batch_id})'
