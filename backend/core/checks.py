"""Startup checks that turn a half-finished module wiring into a loud failure.

Django does not import an app's ``checks`` module on its own — ``django.contrib.*``
imports its own checks from ``apps.py`` — so ``core.apps.CoreConfig.ready`` imports
this module to register them.
"""

from django.conf import settings
from django.core.checks import Error, Tags, register

from core.module_registry import MODULES


@register(Tags.database)
def check_business_module_databases(app_configs, **kwargs):
    """Every business module needs a same-named database alias in ``DATABASES``.

    Two halves have to agree for a module to be isolated: the app-to-alias map and
    the alias itself. The map is derived from ``core.module_registry`` (see
    ``backend/db_router``), so "module registered but not routed" can no longer
    happen; ``DATABASES`` is the hand-written half, and a missing alias does not
    raise at boot — the module's reads and writes go to a connection that either
    does not exist or is the core database, which is how two modules end up sharing
    one file. That is worth catching before the first request, not after.

    All defined modules are checked, not just the enabled ones: disabling is a
    temporary state that one `.env` edit undoes.
    """
    errors = []
    for module in MODULES:
        if module.module_id not in settings.DATABASES:
            errors.append(
                Error(
                    f'Business module {module.module_id!r} has no matching database '
                    f'alias {module.module_id!r}.',
                    hint=(
                        'Add the alias to DATABASES in backend/settings.py and give '
                        f'it a path via the {module.module_id.upper()}_DATABASE_PATH '
                        'setting in .env.'
                    ),
                    id='core.E001',
                )
            )
    return errors
