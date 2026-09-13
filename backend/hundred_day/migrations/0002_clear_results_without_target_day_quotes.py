from django.db import migrations


def clear_results_without_target_day_quotes(apps, schema_editor):
    """Drop derived results whose industry details carry no 涨幅/成交额.

    ``HundredDayIndustrySummary.new_high_stocks`` / ``new_low_stocks`` are plain
    JSON columns, so nothing in the schema changes; but rows written before this
    release only hold ``code`` and ``name``, and the page would render an empty
    「（）」 for them. The stored values are pure derived data that the read path
    rebuilds on demand from local public data (spec §5.8(a)), so clearing them is
    cheaper and safer than back-filling. ``HundredDayRun`` history stays intact.
    """
    apps.get_model('hundred_day', 'HundredDayResult').objects.using(
        schema_editor.connection.alias
    ).all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('hundred_day', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(
            clear_results_without_target_day_quotes,
            migrations.RunPython.noop,
        ),
    ]
