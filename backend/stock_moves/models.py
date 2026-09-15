"""Persistent derived data for the 大涨跌幅与大成交量个股 module."""

from django.db import models


class StockMoveItem(models.Model):
    """One ranked stock inside one of the six published groups.

    这是本模块**唯一一张表**，同时承载"某一天的结果"和"结果里的每只股票"。结果级
    的数字 —— 六组计数、涉及股票去重数、非致命告警 —— 都能由这一天的行算出来，
    所以不再单独存一份：读路径按 ``business_date`` 取行后现算（见
    ``services/read_path.py``）。输入是公共日行情（决定参与股票与涨跌幅）和开盘啦
    行业映射（决定每只股票写进 ``industries`` 的内容）。同一天重跑就是换掉这一天
    的所有行，读路径取到的一定是最近一次写出来的结果。

    页面是"行=市场、列=涨跌"的看板，所以分组键也是这两个维度的组合：上证/深证/
    北交所各自再按涨跌方向拆成两组，共六组。北京证券交易所股票既不冒充深证股票
    （AC-MOVE-008），也不被丢弃 —— 它们满足同一组阈值，只是不属于上证/深证的涨跌
    四组，因此单列成北交所的上涨/下跌两组。
    """

    class Group(models.TextChoices):
        SSE_RISE = 'sse_rise', '上证上涨'
        SSE_FALL = 'sse_fall', '上证下跌'
        SZSE_RISE = 'szse_rise', '深证上涨'
        SZSE_FALL = 'szse_fall', '深证下跌'
        BSE_RISE = 'bse_rise', '北交所上涨'
        BSE_FALL = 'bse_fall', '北交所下跌'

    business_date = models.DateField(verbose_name='业务日期')
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
    # 这一天结果落库的时刻。**故意不用 auto_now_add**：同一天重跑必须刷新它，
    # 因为读路径拿它当文件缓存的缓存身份 —— 不刷新就会在 TTL 内继续发旧报文。
    # 一次构建里这一天的每一行共用同一个值，所以取任意一行都对。
    published_at = models.DateTimeField(verbose_name='发布时间')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['business_date', 'group', 'rank'],
                name='stock_moves_item_date_group_rank_unique',
            ),
            models.UniqueConstraint(
                fields=['business_date', 'stock_code'],
                name='stock_moves_item_date_stock_unique',
            ),
        ]
        indexes = [
            models.Index(
                fields=['business_date', 'group', 'rank'],
                name='stock_moves_day_group_rank_idx',
            )
        ]
        ordering = ['group', 'rank']
        verbose_name = '大涨跌幅与大成交量股票明细'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.business_date} {self.get_group_display()} #{self.rank} {self.stock_code}'
