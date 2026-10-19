"""Register Lowes dryer NULL fields without changing collected data."""
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.common.db import dx_connection, dx_table


def registration_sql():
    script = (Path(settings.BASE_DIR) / 'sql/setup_lowes_dryer_layer2.sql').read_text(encoding='utf-8')
    script = re.sub(r'^(BEGIN|COMMIT);\s*$', '', script, flags=re.MULTILINE)
    for name in ('monitoring_retail_columns', 'monitoring_null_category',
                 'monitoring_null_group', 'monitoring_null_column'):
        script = re.sub(r'\bpublic\.' + name + r'\b', 'public.' + dx_table(name), script)
    return script


class Command(BaseCommand):
    help = 'Idempotently register SEA Lowes dryer NULL configuration.'

    def handle(self, *args, **options):
        with dx_connection() as (connection, cursor):
            cursor.execute(registration_sql())
            counts = cursor.fetchall()
            if counts != [('LDY_DRYER', 11)]:
                raise CommandError(f'Expected 11 Lowes dryer NULL columns, got {counts!r}; rolled back.')
            connection.commit()
        self.stdout.write(self.style.SUCCESS('Lowes LDY_DRYER: 11 NULL columns registered. Source data unchanged.'))
