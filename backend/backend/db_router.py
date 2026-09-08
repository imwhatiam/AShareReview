"""Database isolation for the independently deployable business apps."""


BUSINESS_APP_DATABASES = {
    'kaipanla': 'kaipanla',
    'eastmoney': 'eastmoney',
    'stock_moves': 'stock_moves',
    'sector_momentum': 'sector_momentum',
    'hundred_day': 'hundred_day',
}


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
