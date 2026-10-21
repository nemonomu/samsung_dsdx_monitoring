"""Manual data uses the existing DX PostgreSQL connection, never default SQLite."""
from django.db import transaction
from .models import PostgresManualImage, PostgresManualRevision

DATABASE = 'dx'


class RevisionConflict(Exception):
    pass


def revisions():
    return PostgresManualRevision.objects.using(DATABASE)


def images():
    return PostgresManualImage.objects.using(DATABASE)


def save_revision(version, data, username):
    with transaction.atomic(using=DATABASE):
        latest = revisions().first()
        if version != (latest.version if latest else 0):
            raise RevisionConflict
        # The primary key is the final guard when two requests read the same version.
        return revisions().create(version=version + 1, data=data, created_by=username)
