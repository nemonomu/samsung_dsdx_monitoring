from django.db import models
from django.conf import settings
from django.utils import timezone


def manual_table(name):
    # Match other monitoring data: development never writes production tables.
    return ('test_' if settings.DEBUG else '') + name


class ManualRevision(models.Model):
    """Append-only manual snapshots; the unique version also guards concurrent saves."""

    version = models.PositiveIntegerField(primary_key=True)
    data = models.JSONField()
    created_by = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-version']


class ManualImage(models.Model):
    digest = models.CharField(max_length=64, primary_key=True)
    content = models.BinaryField()
    content_type = models.CharField(max_length=32)
    created_by = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)


class PostgresManualRevision(models.Model):
    version = models.BigIntegerField(primary_key=True)
    data = models.JSONField(db_column='content')
    created_by = models.CharField(max_length=150)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = manual_table('monitoring_dx_manual_revisions')
        ordering = ['-version']


class PostgresManualImage(models.Model):
    digest = models.CharField(max_length=64, primary_key=True, db_column='image_hash')
    content = models.BinaryField(db_column='image_data')
    content_type = models.CharField(max_length=32)
    created_by = models.CharField(max_length=150)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = manual_table('monitoring_dx_manual_images')
