from django.urls import path

from sector_momentum import views

app_name = 'sector_momentum'

urlpatterns = [
    path('', views.results, name='results'),
    path('dates/', views.dates, name='dates'),
]
