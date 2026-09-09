"""Persistent derived data for the 板块动量 module."""

from django.db import models
from django.utils import timezone


class SectorMomentumResult(models.Model):
    """A published momentum analysis for one trading day and source versions."""

    business_date = models.DateField(db_index=True, verbose_name='业务日期')
    source_daily_price_version = models.CharField(max_length=64, verbose_name='公共日行情版本')
    source_industry_version = models.CharField(max_length=64, verbose_name='行业映射版本')
    total_market_turnover = models.DecimalField(
        max_digits=20, decimal_places=4, default=0, verbose_name='全市场成交额'
    )
    unmapped_stock_count = models.PositiveIntegerField(default=0, verbose_name='未映射股票数')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['business_date', 'source_daily_price_version', 'source_industry_version'],
                name='sector_momentum_result_source_version_unique',
            ),
        ]
        indexes = [models.Index(fields=['business_date', 'created_at'])]
        ordering = ['-business_date', '-created_at']
        verbose_name = '板块动量结果'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.business_date} ({self.source_daily_price_version})'


class SectorMomentumRanking(models.Model):
    """One parent-industry ranking in one momentum metric."""

    class Metric(models.TextChoices):
        ABOVE_5PCT = 'above_5pct', '涨幅大于5%'
        TOP_5_PERCENT = 'top_5_percent', '全市场涨幅前5%'

    result = models.ForeignKey(
        SectorMomentumResult,
        on_delete=models.CASCADE,
        related_name='rankings',
        verbose_name='分析结果',
    )
    metric = models.CharField(max_length=16, choices=Metric.choices, verbose_name='分析口径')
    rank = models.PositiveSmallIntegerField(verbose_name='排名')
    industry_code = models.CharField(max_length=32, verbose_name='行业代码')
    industry_name = models.CharField(max_length=64, verbose_name='行业名称')
    stock_count = models.PositiveIntegerField(default=0, verbose_name='股票数量')
    average_change_percent = models.DecimalField(
        max_digits=12, decimal_places=6, default=0, verbose_name='平均涨跌幅'
    )
    industry_turnover = models.DecimalField(
        max_digits=20, decimal_places=4, default=0, verbose_name='行业成交额'
    )
    market_turnover_ratio = models.DecimalField(
        max_digits=16, decimal_places=8, default=0, verbose_name='行业成交额占比'
    )
    score = models.DecimalField(
        max_digits=24, decimal_places=12, default=0, verbose_name='综合评分'
    )
    stocks = models.JSONField(default=list, verbose_name='股票明细')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['result', 'metric', 'rank'],
                name='sector_momentum_metric_rank_unique',
            ),
            models.UniqueConstraint(
                fields=['result', 'metric', 'industry_code'],
                name='sector_momentum_metric_industry_unique',
            ),
        ]
        ordering = ['metric', 'rank']
        verbose_name = '板块动量行业排行'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.get_metric_display()} #{self.rank} {self.industry_name}'


class SectorMomentumRun(models.Model):
    """An independent execution record for one build attempt."""

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
    total_market_turnover = models.DecimalField(
        max_digits=20, decimal_places=4, default=0, verbose_name='全市场成交额'
    )
    unmapped_stock_count = models.PositiveIntegerField(default=0, verbose_name='未映射股票数')
    started_at = models.DateTimeField(default=timezone.now, verbose_name='开始时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')
    error_summary = models.TextField(blank=True, verbose_name='错误摘要')

    class Meta:
        indexes = [
            models.Index(fields=['business_date', 'started_at']),
            models.Index(fields=['status', 'started_at']),
        ]
        ordering = ['-started_at']
        verbose_name = '板块动量运行记录'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.business_date} {self.status} ({self.source_batch_id})'
