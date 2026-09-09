from django.urls import path

from core import views

app_name = 'core'

urlpatterns = [
    path('session/', views.session, name='session'),
    path('login/', views.login, name='login'),
    path('logout/', views.logout, name='logout'),
    path('health/', views.health, name='health'),
    path('modules/', views.modules, name='modules'),
]
