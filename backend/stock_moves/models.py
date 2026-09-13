"""Persistent derived data for the 大涨跌幅与大成交量个股 module."""

from django.db import models
from django.utils import timezone


class StockMoveResult(models.Model):
    """One published six-group analysis derived from two public datasets.

    输入是**两个**公共数据集：公共日行情（决定参与股票与涨跌幅）和开盘啦行业
    映射（决定每只股票写进 ``industries`` 的内容）。两个版本都要记下来，否则
    只重跑行业映射时既看不出结果已经落后，也不会重建。
    """

    business_date = models.DateField(db_index=True, verbose_name='业务日期')
    source_daily_price_version = models.CharField(
        max_length=64, db_index=True, verbose_name='公共日行情版本'
    )
    source_industry_version = models.CharField(
        max_length=64, db_index=True, verbose_name='行业映射版本'
    )
    sse_rise_count = models.PositiveIntegerField(default=0, verbose_name='上证上涨组数量')
    sse_fall_count = models.PositiveIntegerField(default=0, verbose_name='上证下跌组数量')
    szse_rise_count = models.PositiveIntegerField(default=0, verbose_name='深证上涨组数量')
    szse_fall_count = models.PositiveIntegerField(default=0, verbose_name='深证下跌组数量')
    bse_rise_count = models.PositiveIntegerField(default=0, verbose_name='北交所上涨组数量')
    bse_fall_count = models.PositiveIntegerField(default=0, verbose_name='北交所下跌组数量')
    distinct_stock_count = models.PositiveIntegerField(default=0, verbose_name='涉及股票去重数量')
    warnings = models.JSONField(default=list, verbose_name='非致命分析警告')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'business_date',
                    'source_daily_price_version',
                    'source_industry_version',
                ],
                name='stock_moves_result_source_versions_unique',
            )
        ]
        indexes = [models.Index(fields=['business_date', 'created_at'])]
        ordering = ['-business_date', '-created_at']
        verbose_name = '大涨跌幅与大成交量结果'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.business_date} ({self.source_daily_price_version})'


class StockMoveItem(models.Model):
    """A ranked stock inside one of the published groups.

    页面是"行=市场、列=涨跌"的看板，所以分组键也是这两个维度的组合：
    上证/深证/北交所各自再按涨跌方向拆成两组，共六组。北京证券交易所股票
    既不冒充深证股票（AC-MOVE-008），也不被丢弃 —— 它们满足同一组阈值，
    只是不属于上证/深证的涨跌四组，因此单列成北交所的上涨/下跌两组。
    """

    class Group(models.TextChoices):
        SSE_RISE = 'sse_rise', '上证上涨'
        SSE_FALL = 'sse_fall', '上证下跌'
        SZSE_RISE = 'szse_rise', '深证上涨'
        SZSE_FALL = 'szse_fall', '深证下跌'
        BSE_RISE = 'bse_rise', '北交所上涨'
        BSE_FALL = 'bse_fall', '北交所下跌'

    result = models.ForeignKey(
        StockMoveResult,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='分析结果',
    )
    group = models.CharField(max_length=9, choices=Group.choices, verbose_name='分组')
    rank = models.PositiveIntegerField(verbose_name='组内排序')
    stock_code = models.CharField(max_length=6, verbose_name='股票代码')
    stock_name = models.CharField(max_length=64, verbose_name='股票名称')
    industries = models.JSONField(default=list, verbose_name='所属行业快照')
    change_percent = models.DecimalField(
        max_digits=12, decimal_places=6, verbose_name='涨跌幅（%）'
    )
    turnover = models.DecimalField(
        max_digits=24, decimal_places=4, verbose_name='成交额（元）'
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['result', 'group', 'rank'],
                name='stock_moves_item_result_group_rank_unique',
            ),
            models.UniqueConstraint(
                fields=['result', 'stock_code'],
                name='stock_moves_item_result_stock_unique',
            ),
        ]
        indexes = [models.Index(fields=['result', 'group', 'rank'])]
        ordering = ['group', 'rank']
        verbose_name = '大涨跌幅与大成交量股票明细'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.get_group_display()} #{self.rank} {self.stock_code}'


class StockMoveRun(models.Model):
    """An independently observable execution record for one analysis attempt."""

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
    source_industry_version = models.CharField(
        max_length=64, blank=True, verbose_name='行业映射版本'
    )
    published_result_id = models.PositiveBigIntegerField(
        null=True, blank=True, verbose_name='已发布结果标识'
    )
    total_candidate_count = models.PositiveIntegerField(default=0, verbose_name='涉及股票去重数量')
    started_at = models.DateTimeField(default=timezone.now, verbose_name='开始时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')
    error_summary = models.TextField(blank=True, verbose_name='错误摘要')

    class Meta:
        indexes = [
            models.Index(fields=['business_date', 'started_at']),
            models.Index(fields=['status', 'started_at']),
        ]
        ordering = ['-started_at']
        verbose_name = '大涨跌幅与大成交量运行记录'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.business_date} {self.status} ({self.source_batch_id})'
