from django.urls import path

from stock_moves import views

app_name = 'stock_moves'

urlpatterns = [
    path('', views.results, name='results'),
    path('dates/', views.dates, name='dates'),
]
