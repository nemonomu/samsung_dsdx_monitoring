from django.core.management.base import BaseCommand, CommandError
from apps.dx.dx_layer1.column_statistics.services import catalog
from apps.dx.dx_layer1.collection_issues.services import refresh_target


def refresh_all(*, country=None, report=None):
    errors = 0
    for source in catalog():
        if country and source['country'] != country:
            continue
        for retailer in source['retailers']:
            job = (source['country'], source['product'], retailer)
            try:
                result = refresh_target(*job)
                if report:
                    report(' '.join(job) + f": days={result['days']}, busy={result['busy']}")
            except Exception:
                errors += 1
                if report:
                    report(' '.join(job) + ': query failed; existing incidents retained')
    return errors


class Command(BaseCommand):
    help = 'Check source-day collection issues from 2026-09-01, retaining unresolved incidents.'

    def add_arguments(self, parser):
        parser.add_argument('--country', choices=sorted({s['country'] for s in catalog()}))

    def handle(self, *args, **options):
        errors = refresh_all(country=options['country'], report=self.stdout.write)
        if errors:
            raise CommandError(f'{errors} targets failed; retry required.')
