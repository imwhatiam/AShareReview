"""行业快照只剩一层，把 ``parent_industries`` 正名为 ``industries``。

**为什么必须手写而不是让 ``makemigrations`` 生成** —— 两个坑叠加：

1. ``makemigrations`` 在非交互模式下会把"删旧字段 + 加新字段"当成 remove + add，
   那样会丢掉已有 662 行个股标志里的行业快照，还要重建全部产物。
2. 更隐蔽的是：Django 在 SQLite 上把 ``RenameField`` 生成成 ``-- (no-op)``
   （实测 ``sqlmigrate`` 输出确认），**迁移报 OK 但列名一个字都没改**。所以这里用
   ``SeparateDatabaseAndState``：数据库层跑真正的 ``ALTER TABLE ... RENAME COLUMN``
   （SQLite 3.25+ 支持、原地改名保留数据），状态层记录字段改名。
"""

from django.db import migrations, models

TABLE = 'hundred_day_hundreddaystockflag'


class Migration(migrations.Migration):

    dependencies = [
        ('hundred_day', '0002_clear_results_without_target_day_quotes'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=f'ALTER TABLE {TABLE} RENAME COLUMN parent_industries TO industries;',
                    reverse_sql=f'ALTER TABLE {TABLE} RENAME COLUMN industries TO parent_industries;',
                ),
            ],
            state_operations=[
                migrations.RenameField(
                    model_name='hundreddaystockflag',
                    old_name='parent_industries',
                    new_name='industries',
                ),
            ],
        ),
        migrations.AlterField(
            model_name='hundreddaystockflag',
            name='industries',
            field=models.JSONField(default=list, verbose_name='所属行业快照'),
        ),
    ]
