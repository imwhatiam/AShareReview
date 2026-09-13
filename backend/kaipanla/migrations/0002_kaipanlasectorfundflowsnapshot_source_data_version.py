"""Add the publication version to every snapshot row.

Why the column exists: the write path commits the rows and *then* marks the
``DataVersion`` complete. If the process dies (or the second write fails) inside
that window, the rows are already visible while the version is still ``running``.
The read path picks the newest **complete** version and then takes the newest row
by ``Max(snapshot_time)`` — so it would return the unpublished rows under the
older version's name and cache them under that version's key.

Stamping the version on the rows makes the two impossible to mix: the read path
only ever serves rows whose version is in the set of complete publications.

``blank``/``default=''`` keeps the column addition non-null-safe, and the data
migration below backfills the rows that already exist.
"""

from django.db import migrations, models

DATASET_KEY = 'kaipanla_sector_fund_flow'


def backfill_source_data_version(apps, schema_editor):
    """Stamp existing rows with the version that published their trading day.

    Old code wrote the rows and published immediately afterwards, so every
    pre-existing row belongs to the newest complete version of *its own* trading
    day — that is exactly what is written here, day by day.

    Rows whose day has no complete version at all (an orphan left by a crash, or
    a day whose publication failed) are deliberately left empty: an empty version
    is never in the published set, so the read path treats them as unpublished,
    which is precisely what they are. Those days are re-collected by the normal
    command.
    """
    Snapshot = apps.get_model('kaipanla', 'KaipanlaSectorFundFlowSnapshot')
    DataVersion = apps.get_model('core', 'DataVersion')
    alias = schema_editor.connection.alias

    trade_dates = (
        Snapshot.objects.using(alias)
        .filter(source_data_version='')
        .values_list('trade_date', flat=True)
        .distinct()
    )
    for trade_date in list(trade_dates):
        # DataVersion 属于 core，始终在 default 库（见 backend/db_router.py），
        # 所以这里显式换库读，而不是走 schema_editor 的连接。
        version = (
            DataVersion.objects.using('default')
            .filter(
                dataset_key=DATASET_KEY,
                status='complete',
                business_date=trade_date,
            )
            .order_by('-finished_at', '-started_at')
            .values_list('version', flat=True)
            .first()
        )
        if version is None:
            continue
        Snapshot.objects.using(alias).filter(
            trade_date=trade_date, source_data_version=''
        ).update(source_data_version=version)


class Migration(migrations.Migration):

    dependencies = [
        ('kaipanla', '0001_initial'),
        ('core', '0004_remove_industry_level'),
    ]

    operations = [
        migrations.AddField(
            model_name='kaipanlasectorfundflowsnapshot',
            name='source_data_version',
            field=models.CharField(
                blank=True, db_index=True, default='', max_length=64, verbose_name='数据版本'
            ),
        ),
        migrations.RunPython(backfill_source_data_version, migrations.RunPython.noop),
    ]
