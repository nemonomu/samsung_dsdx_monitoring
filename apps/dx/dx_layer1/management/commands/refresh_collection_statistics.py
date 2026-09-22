from datetime import date, timedelta, timezone as tz
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from apps.dx.dx_layer1.collection_statistics.calculations import COUNTRIES, OFFSETS
from apps.dx.dx_layer1.collection_statistics.collector import refresh_country


class Command(BaseCommand):
    help = 'Precompute Layer1 collection statistics outside web requests (source dates).'

    def add_arguments(self, parser):
        parser.add_argument('--country', choices=COUNTRIES)
        parser.add_argument('--start', type=date.fromisoformat)
        parser.add_argument('--end', type=date.fromisoformat)
        parser.add_argument('--days', type=int, default=3)
        parser.add_argument('--automatic', action='store_true', help='Refresh recent counts and gradually fill missing history.')

    def handle(self, *args, **options):
        if options['automatic']:
            if options['start'] or options['end'] or options['days'] != 3:
                raise CommandError('--automatic cannot be combined with date ranges or --days')
            from apps.dx.dx_layer1.collection_statistics.automatic import refresh_automatic
            def report(country, phase, result):
                self.stdout.write(f"{country} {phase}: updated={result['updated']}, errors={result['errors']}, busy={result['busy']}")
            errors = refresh_automatic(timezone.localdate(timezone=tz(timedelta(hours=9))),
                countries=[options['country']] if options['country'] else COUNTRIES, report=report)
            if errors:
                raise CommandError(f'{errors} source-day refreshes failed; the next scheduled run will retry.')
            return
        if not 1 <= options['days'] <= 120:
            raise CommandError('--days must be between 1 and 120')
        today = timezone.localdate(timezone=tz(timedelta(hours=9)))
        errors = 0
        for country in ([options['country']] if options['country'] else COUNTRIES):
            end = options['end'] or today - timedelta(days=OFFSETS[country])
            start = options['start'] or end - timedelta(days=options['days'] - 1)
            if start > end or (end - start).days > 119:
                raise CommandError('Choose a source-date range of at most 120 days')
            result = refresh_country(country, start, end, today=today)
            self.stdout.write(f"{country}: updated={result['updated']}, errors={result['errors']}, busy={result['busy']}")
            errors += result['errors']
        if errors:
            raise CommandError(f'{errors} source-day refreshes failed; last good snapshots were preserved.')
