"""Persistent derived data for the 百日新高新低占比 module.

三张表，三个粒度，一个都不能再少：

- :class:`HundredDayBreadth` —— 交易日粒度。某个业务日期这一次发布，连同它
  往前 100 个交易日的市场宽度（页面上的趋势图就是这些行）。
- :class:`HundredDayStockFlag` —— 股票粒度。被标记的每一只股票。
- :class:`HundredDayIndustrySummary` —— 行业粒度。只留 ``stock_count``。

为什么不能再并成一张：``valid_stock_count``（当日全市场有效交易股票数）、行业的
``stock_count``（含**未被标记**的成分股）和趋势的 100 个点，都无法从被标记股票的
行里推出来。要让它们都能聚合出来，唯一一张表就得装下全部 5,571 只股票 × 最近 100
个交易日（约 55.7 万行/发布日，对比现在 535 行），那等于把 ``core`` 的日线整段复制
进模块库。所以这里是三个粒度各自的落库点，跨粒度能算的不再存第二份。
"""

from django.core.exceptions import ValidationError
from django.db import models


class HundredDayBreadth(models.Model):
    """One trading day's market breadth, published under one business date.

    ``HundredDayResult`` 与 ``HundredDayTrend`` 合并成了这一张表：它们本来就是
    同一个粒度，而且业务日期那一行的三个数值与"当日结果"逐字段相等（趋势点只是
    多了两个比值，比值由除法得出）。所以页面上的"当日"就是 ``trade_date`` 等于
    ``business_date`` 的那一行，"趋势"就是同一个 ``business_date`` 下的全部行。

    ``business_date`` 是这次发布的键（重跑换掉这一天的全部行），``trade_date``
    是这一行数据自己的交易日 —— 与 kaipanla 快照同时带 ``trade_date`` 和
    ``snapshot_time`` 是同一个道理。
    """

    business_date = models.DateField(verbose_name='业务日期')
    trade_date = models.DateField(verbose_name='交易日期')
    valid_stock_count = models.PositiveIntegerField(default=0, verbose_name='有效股票数')
    new_high_count = models.PositiveIntegerField(default=0, verbose_name='新高数量')
    new_low_count = models.PositiveIntegerField(default=0, verbose_name='新低数量')
    # 这一次发布的时刻。**故意不用 auto_now_add**：重跑同一天必须刷新它，
    # 因为读路径拿它当文件缓存的缓存身份 —— 不刷新就会在 TTL 内继续发旧报文。
    published_at = models.DateTimeField(verbose_name='发布时间')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['business_date', 'trade_date'],
                name='hundred_day_breadth_date_trade_date_unique',
            ),
        ]
        indexes = [
            models.Index(
                fields=['business_date', 'trade_date'],
                name='hundred_day_day_trade_date_idx',
            )
        ]
        ordering = ['trade_date']
        verbose_name = '百日市场宽度'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.business_date} @ {self.trade_date}'


class HundredDayStockFlag(models.Model):
    """A stock-level flag: the single place a flagged stock is stored.

    这只表是**被标记股票的唯一存放点**。行业明细里每只股票要展示的涨幅与成交额也
    在这里（``change_percent`` / ``turnover``），而不是在行业汇总表里再存一份 JSON：
    行业归属是快照，必须随标记一起落库，所以它不能读时去 ``core`` 现查。行业维度的
    明细列表与新高/新低计数都由读路径按 ``industries`` 分组重建，与写入时逐行业
    展开的结果一致。
    """

    business_date = models.DateField(verbose_name='业务日期')
    stock_code = models.CharField(max_length=6, verbose_name='股票代码')
    stock_name = models.CharField(max_length=64, verbose_name='股票名称')
    industries = models.JSONField(default=list, verbose_name='所属行业快照')
    is_new_high = models.BooleanField(default=False, verbose_name='是否新高')
    is_new_low = models.BooleanField(default=False, verbose_name='是否新低')
    change_percent = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True,
        verbose_name='涨跌幅（%）',
    )
    turnover = models.DecimalField(
        max_digits=24,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name='成交额（元）',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['business_date', 'stock_code'],
                name='hundred_day_date_stock_unique',
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
        return f'{self.business_date} {self.stock_code}'


class HundredDayIndustrySummary(models.Model):
    """Parent-industry aggregates for one trading day.

    这里只留**行业级**事实：成分股数量。它含**未被标记**的成分股（例如 36 只
    成分股、0 新高 0 新低），所以从个股标志里推不出来，必须落库。行业级的新高/
    新低数量则属于个股标志的函数，读时按 ``industries`` 分组现算，与行业名单
    来自同一次分组，因此计数与名单永远不会互相矛盾。
    """

    business_date = models.DateField(verbose_name='业务日期')
    industry_code = models.CharField(max_length=32, verbose_name='行业代码')
    industry_name = models.CharField(max_length=64, verbose_name='行业名称')
    stock_count = models.PositiveIntegerField(default=0, verbose_name='行业股票数')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['business_date', 'industry_code'],
                name='hundred_day_date_industry_unique',
            ),
        ]
        ordering = ['industry_code']
        verbose_name = '百日新高新低板块汇总'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.business_date} {self.industry_name}'
