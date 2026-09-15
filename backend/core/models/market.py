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


class IndustrySnapshot(models.Model):
    industry_code = models.CharField(max_length=32, unique=True)
    industry_name = models.CharField(max_length=64)
    stock_codes = models.JSONField(default=list)

    class Meta:
        ordering = ['industry_code']
