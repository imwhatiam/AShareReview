from django.urls import path

from hundred_day import views

app_name = 'hundred_day'

urlpatterns = [
    path('', views.results, name='results'),
    path('dates/', views.dates, name='dates'),
]
