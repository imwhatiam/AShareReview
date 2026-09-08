from django.db import models


class Stock(models.Model):
    class Exchange(models.TextChoices):
        SSE = 'sse', '上海证券交易所'
        SZSE = 'szse', '深圳证券交易所'
        BSE = 'bse', '北京证券交易所'

    thscode = models.CharField(max_length=32, unique=True)
    stock_code = models.CharField(max_length=6, unique=True)
    stock_name = models.CharField(max_length=64)
    exchange = models.CharField(max_length=4, choices=Exchange.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['stock_code']


class TradingDay(models.Model):
    trade_date = models.DateField(unique=True)

    class Meta:
        ordering = ['trade_date']


class IndustrySnapshot(models.Model):
    class Level(models.TextChoices):
        PARENT = 'parent', '父行业'
        CHILD = 'child', '子行业'

    industry_code = models.CharField(max_length=32, unique=True)
    industry_name = models.CharField(max_length=64)
    industry_level = models.CharField(max_length=6, choices=Level.choices)
    stock_codes = models.JSONField(default=list)

    class Meta:
        ordering = ['industry_level', 'industry_code']
