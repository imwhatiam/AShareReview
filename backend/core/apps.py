from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Django 不会自动导入各 app 的 `checks` 模块（django.contrib.* 也是在自己的
        # apps.py 里显式 import），所以在这里注册；`manage.py check` / `test` / 每个
        # 管理命令启动时都会跑一遍。
        from core import checks  # noqa: F401
