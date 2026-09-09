"""Kaipanla API routes."""

from django.urls import path

from kaipanla import views

app_name = 'kaipanla'

urlpatterns = [
    path('sectors/', views.sectors, name='sectors'),
    path('sectors/intraday/', views.intraday, name='intraday'),
    path('sectors/intraday/history/', views.intraday_history, name='intraday-history'),
    path('dates/', views.dates, name='dates'),
]
