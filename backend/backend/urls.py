"""
URL configuration for backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path

from core.module_registry import get_enabled_modules
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path, re_path

from core.module_registry import MODULES, get_enabled_modules
from core.views import module_disabled_view

enabled_modules = get_enabled_modules()

urlpatterns = [
    path('api/core/', include('core.urls')),
    path('admin/', admin.site.urls),
]

for module in enabled_modules:
    urlpatterns.append(
        path(module.api_prefix.removeprefix('/'), include(module.urlconf))
    )

# 被关掉的模块必须自己回答：落到 Django 默认 HTML 404 的话，调用方既拿不到统一
# JSON 外壳，也分不清"模块没启用"和"URL 不存在"。前缀互斥，所以注册顺序无关。
_enabled_ids = {module.module_id for module in enabled_modules}
for module in MODULES:
    if module.module_id in _enabled_ids:
        continue
    urlpatterns.append(
        re_path(
            rf'^{module.api_prefix.removeprefix("/")}.*$',
            module_disabled_view(module),
        )
    )
