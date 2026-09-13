"""Database isolation for the independently deployable business apps."""

from core.module_registry import MODULES

# 每个业务模块自带一个**同名**数据库别名，所以这份映射是恒等映射。它从模块注册表
# 推导，而不是手写第二份清单：手写时"注册表加了模块、这里忘了加"不会报错 ——
# `_database_for_app` 会把未知 app 静默回退到 `default`，于是新模块的行被写进
# core 库，而过去唯一的路由守护用例只覆盖了 kaipanla。
#
# 回退到 `default` 本身是对的：core 与 django.contrib.* 就应该待在默认库。
BUSINESS_APP_DATABASES = {module.module_id: module.module_id for module in MODULES}


class AppDatabaseRouter:
    """Keep each business app in its own SQLite database."""

    @staticmethod
    def _database_for_app(app_label: str) -> str:
        return BUSINESS_APP_DATABASES.get(app_label, 'default')

    def db_for_read(self, model, **hints):
        return self._database_for_app(model._meta.app_label)

    def db_for_write(self, model, **hints):
        return self._database_for_app(model._meta.app_label)

    def allow_relation(self, obj1, obj2, **hints):
        return self._database_for_app(obj1._meta.app_label) == self._database_for_app(
            obj2._meta.app_label
        )

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return self._database_for_app(app_label) == db
