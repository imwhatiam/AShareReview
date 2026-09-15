"""Persistent derived data for the 板块动量 module."""

from django.db import models


class SectorMomentumRanking(models.Model):
    """One parent-industry ranking in one momentum metric.

    这是本模块**唯一一张表**，同时承载"某一天的结果"和"结果里的每个行业"。

    结果里除了行业本身，只剩两件**日级**事实需要落库：``total_market_turnover``
    与 ``unmapped_stock_count``。它们是当日全市场的口径，推不出来，所以按行重复
    存一份（一天最多 20 行，可以忽略）。

    其余六个数 —— ``rank`` / ``stock_count`` / ``average_change_percent`` /
    ``industry_turnover`` / ``market_turnover_ratio`` / ``score`` —— 都是
    ``stocks`` 加 ``total_market_turnover`` 的函数，读时现算（见
    ``services/read_path.py``）。所以 ``stocks`` 这份明细必须留在表里：它是这些
    数字的唯一来源，也是"同一件事只存一次"里那一次。
    """

    class Metric(models.TextChoices):
        ABOVE_5PCT = 'above_5pct', '涨幅大于5%'
        TOP_5_PERCENT = 'top_5_percent', '全市场涨幅前5%'

    business_date = models.DateField(verbose_name='业务日期')
    metric = models.CharField(max_length=16, choices=Metric.choices, verbose_name='分析口径')
    industry_code = models.CharField(max_length=32, verbose_name='行业代码')
    industry_name = models.CharField(max_length=64, verbose_name='行业名称')
    stocks = models.JSONField(default=list, verbose_name='股票明细')
    total_market_turnover = models.DecimalField(
        max_digits=20, decimal_places=4, default=0, verbose_name='全市场成交额'
    )
    unmapped_stock_count = models.PositiveIntegerField(default=0, verbose_name='未映射股票数')
    # 这一天结果落库的时刻。**故意不用 auto_now_add**：同一天重跑必须刷新它，
    # 因为读路径拿它当文件缓存的缓存身份 —— 不刷新就会在 TTL 内继续发旧报文。
    # 一次构建里这一天的每一行共用同一个值，所以取任意一行都对。
    published_at = models.DateTimeField(verbose_name='发布时间')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['business_date', 'metric', 'industry_code'],
                name='sector_momentum_date_metric_industry_unique',
            ),
        ]
        indexes = [
            models.Index(
                fields=['business_date', 'metric'],
                name='sector_momentum_day_metric_idx',
            )
        ]
        # 名次不落库，所以库里的顺序按（口径, 行业代码）稳定排列；报文里的
        # ``rank`` 由读路径按综合评分重排得出。
        ordering = ['metric', 'industry_code']
        verbose_name = '板块动量行业排行'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.business_date} {self.get_metric_display()} {self.industry_name}'
