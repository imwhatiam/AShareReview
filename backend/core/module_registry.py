"""Static metadata for optional business modules."""

from dataclasses import asdict, dataclass

from django.core.exceptions import ImproperlyConfigured

from backend.env import get_list_setting


@dataclass(frozen=True)
class ModuleDefinition:
    module_id: str
    display_name: str
    app_config: str
    urlconf: str
    frontend_route: str
    api_prefix: str
    navigation_group: str
    navigation_order: int
    requires_login: bool = True

    def as_api_dict(self) -> dict[str, object]:
        data = asdict(self)
        data.pop('app_config')
        data.pop('urlconf')
        data['id'] = data.pop('module_id')
        data['enabled'] = True
        return data


MODULES = (
    ModuleDefinition(
        'kaipanla', '开盘啦', 'kaipanla.apps.KaipanlaConfig', 'kaipanla.urls',
        '/fund-flow/kaipanla', '/api/kaipanla/', 'fund_flow', 10,
    ),
    ModuleDefinition(
        'stock_moves', '大涨跌幅与大成交量个股', 'stock_moves.apps.StockMovesConfig',
        'stock_moves.urls', '/stock-moves', '/api/stock-moves/', 'analysis', 20,
    ),
    ModuleDefinition(
        'sector_momentum', '板块动量',
        'sector_momentum.apps.SectorMomentumConfig', 'sector_momentum.urls',
        '/sector-momentum', '/api/sector-momentum/', 'analysis', 30,
    ),
    ModuleDefinition(
        'hundred_day', '百日新高新低占比', 'hundred_day.apps.HundredDayConfig',
        'hundred_day.urls', '/hundred-day', '/api/hundred-day/', 'analysis', 40,
    ),
)
MODULES_BY_ID = {module.module_id: module for module in MODULES}


def get_enabled_modules() -> tuple[ModuleDefinition, ...]:
    enabled_ids = get_list_setting(
        'ENABLED_MODULES', tuple(module.module_id for module in MODULES)
    )
    unknown_ids = set(enabled_ids) - MODULES_BY_ID.keys()
    if unknown_ids:
        names = ', '.join(sorted(unknown_ids))
        raise ImproperlyConfigured(f'Unknown module IDs in ENABLED_MODULES: {names}.')
    if not enabled_ids:
        # 空列表不是"合法的空配置"：它会让 INSTALLED_APPS 与 URLconf 同时丢掉全部业务
        # 模块，页面变成 404 而启动不报错。这类配置错误必须在启动时炸出来。
        raise ImproperlyConfigured(
            'ENABLED_MODULES resolved to no modules; at least one business module must '
            'be enabled. Delete the setting (or list the module IDs) instead of '
            'leaving it empty.'
        )
    return tuple(
        module for module in MODULES if module.module_id in set(enabled_ids)
    )


def get_enabled_app_configs() -> list[str]:
    return [module.app_config for module in get_enabled_modules()]
