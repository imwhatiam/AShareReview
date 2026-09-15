from django.db import migrations


class Migration(migrations.Migration):
    """Drop the mirrored trading calendar.

    ``chinese-calendar`` is now the single source of truth for trading days, so
    the table that mirrored an upstream REST calendar has no writer left.
    """

    dependencies = [
        ('core', '0004_remove_industry_level'),
    ]

    operations = [
        migrations.DeleteModel(
            name='TradingDay',
        ),
    ]
