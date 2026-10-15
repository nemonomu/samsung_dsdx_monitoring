"""Register HomeDepot dryer format, duplicate and cross-field configuration."""
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from apps.common.db import dx_connection, dx_table

EXPECTED = [('crossfield', 7), ('duplicate', 1), ('format', 10)]


def registration_sql():
    script = (Path(settings.BASE_DIR) / 'sql/setup_homedepot_dryer_validation.sql').read_text(encoding='utf-8')
    script = re.sub(r'^(BEGIN|COMMIT);\s*$', '', script, flags=re.MULTILINE)
    # Layer 2 uses environment-specific tables. Layer 3 currently reads the
    # shared monitoring_validation_rules table in both environments.
    for name in ('monitoring_retail_columns', 'monitoring_format_templates',
                 'monitoring_format_rules'):
        script = re.sub(r'\bpublic\.' + name + r'\b', 'public.' + dx_table(name), script)
    return script


class Command(BaseCommand):
    help = 'Register 10 HomeDepot dryer format fields, item duplicate key and 7 cross-field rules.'

    def handle(self, *args, **options):
        with dx_connection() as (connection, cursor):
            cursor.execute(registration_sql())
            counts = cursor.fetchall()
            if counts != EXPECTED:
                raise CommandError(f'Expected {EXPECTED!r}, got {counts!r}; rolled back.')
            connection.commit()
        self.stdout.write(self.style.SUCCESS('HomeDepot LDY_DRYER validation registered. Source data unchanged.'))
