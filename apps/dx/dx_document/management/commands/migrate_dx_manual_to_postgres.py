"""Copy legacy local manual records without deleting or overwriting either source."""
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from apps.dx.dx_document.models import ManualImage, ManualRevision
from apps.dx.dx_document import manual_storage as storage


class Command(BaseCommand):
    help = 'Copy SQLite manual history/images to existing PostgreSQL tables (dry-run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Commit the verified copy to PostgreSQL.')

    def handle(self, *args, **options):
        # Verify both destination tables even if this deployment has no legacy edits.
        try:
            storage.revisions().exists()
            storage.images().exists()
        except Exception as exc:
            raise CommandError('DX manual PostgreSQL tables are unavailable. Check DDL, database permissions and the DEBUG test_ prefix.') from exc
        source_tables = connections['default'].introspection.table_names()
        source_images = ManualImage.objects.using('default').order_by('digest') if ManualImage._meta.db_table in source_tables else []
        source_revisions = ManualRevision.objects.using('default').order_by('version') if ManualRevision._meta.db_table in source_tables else []
        image_count = revision_count = 0
        with transaction.atomic(using=storage.DATABASE):
            for source in source_images:
                target = storage.images().filter(digest=source.digest).first()
                if target:
                    if bytes(target.content) != bytes(source.content) or target.content_type != source.content_type:
                        raise CommandError(f'Conflicting image {source.digest}; no data copied.')
                    continue
                image_count += 1
                if options['apply']:
                    storage.images().create(digest=source.digest, content=bytes(source.content),
                                            content_type=source.content_type, created_by=source.created_by,
                                            created_at=source.created_at)
            for source in source_revisions:
                target = storage.revisions().filter(version=source.version).first()
                if target:
                    if target.data != source.data or target.created_by != source.created_by or target.created_at != source.created_at:
                        raise CommandError(f'Conflicting revision {source.version}; no data copied. Resolve the two histories before switching storage.')
                    continue
                revision_count += 1
                if options['apply']:
                    storage.revisions().create(version=source.version, data=source.data,
                                               created_by=source.created_by, created_at=source.created_at)
        mode = 'Copied' if options['apply'] else 'Would copy (use --apply)'
        self.stdout.write(f'{mode}: {revision_count} revisions, {image_count} images. SQLite source unchanged.')
