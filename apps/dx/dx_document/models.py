from django.db import models


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
