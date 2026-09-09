"""Eastmoney API routes."""

from django.urls import path

from eastmoney import views

app_name = 'eastmoney'

urlpatterns = [
    path('sectors/', views.sectors, name='sectors'),
    path('sectors/intraday/', views.intraday, name='intraday'),
    path('sectors/intraday/history/', views.intraday_history, name='intraday-history'),
    path('dates/', views.dates, name='dates'),
]
