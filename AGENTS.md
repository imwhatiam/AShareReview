# Repository Guidelines

## Project Structure & Module Organization

This repository currently contains a minimal Django backend. The repository root holds project documentation and local configuration. Application code lives under `backend/`:

- `backend/manage.py` — Django command entry point.
- `backend/backend/settings.py` — project settings, database, middleware, and installed apps.
- `backend/backend/urls.py` — root URL routing.
- `backend/backend/asgi.py` and `wsgi.py` — deployment entry points.

Create new Django apps inside `backend/` (for example, `backend/market_review/`). Keep each app’s models, views, URLs, migrations, and tests together. Do not commit generated databases, virtual environments, caches, or `.env` files.

## Build, Test, and Development Commands

Run commands from `backend/` unless noted otherwise:

- `python manage.py runserver` — start the local development server.
- `python manage.py migrate` — apply database migrations to the local SQLite database.
- `python manage.py makemigrations` — generate migrations after model changes; review generated files before committing.
- `python manage.py test` — run the Django test suite.
- `python manage.py check` — validate project configuration without starting the server.

The repository does not yet include a pinned dependency file. Use a virtual environment and document any new dependency in a committed requirements or project configuration file.

## Coding Style & Naming Conventions

Follow PEP 8 with four-space indentation. Use `snake_case` for modules, functions, and variables; `PascalCase` for classes; and descriptive lowercase Django app names. Keep settings environment-specific and avoid embedding credentials. Prefer small views and move reusable business logic into clearly named service modules.

## Testing Guidelines

Use Django’s `TestCase` and test runner. Place tests in an app-level `tests.py` or `tests/` package, naming files `test_*.py` and methods `test_<behavior>`. Add tests for models, routes, permissions, and regressions. Run `python manage.py test` and `python manage.py check` before opening a pull request.

## Commit & Pull Request Guidelines

Existing history uses short, imperative summaries such as `django admin start project backend`. Keep commits focused and use concise present-tense subjects. Pull requests should explain the purpose, summarize key changes, list verification commands, and link related issues. Include screenshots only for user-visible changes and call out migrations or configuration updates explicitly.

## Security & Configuration

Never commit secrets or production credentials. Keep `.env` local, disable `DEBUG` in production, configure `ALLOWED_HOSTS`, and move the Django secret key to environment-based configuration before deployment.
