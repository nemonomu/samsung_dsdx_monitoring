"""Register only the seven approved Bestbuy dryer cross-field rules."""
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from apps.common.db import dx_connection, dx_table


def registration_sql():
    script = (Path(settings.BASE_DIR) / 'sql/setup_bestbuy_dryer_crossfield.sql').read_text(encoding='utf-8')
    script = re.sub(r'^(BEGIN|COMMIT);\s*$', '', script, flags=re.MULTILINE)
    return script.replace('public.monitoring_validation_rules', 'public.' + dx_table('monitoring_validation_rules'))


class Command(BaseCommand):
    help = 'Idempotently register seven SEA Bestbuy dryer cross-field rules.'

    def handle(self, *args, **options):
        with dx_connection() as (connection, cursor):
            cursor.execute(registration_sql())
            counts = cursor.fetchall()
            if counts != [('sea_ldy_dryer_retail', 7)]:
                raise CommandError(f'Expected 7 Bestbuy dryer rules, got {counts!r}; rolled back.')
            connection.commit()
        self.stdout.write(self.style.SUCCESS('Bestbuy LDY_DRYER: 7 cross-field rules registered. Source data unchanged.'))
