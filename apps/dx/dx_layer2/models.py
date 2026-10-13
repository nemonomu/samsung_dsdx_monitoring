from django.db import models


class FormatReviewScope(models.Model):
    """Review metadata lives in Django's DB, separate from collected source rows."""

    fingerprint = models.CharField(max_length=64, unique=True)
    context = models.JSONField()
    revision = models.PositiveIntegerField(default=0)
    policies = models.JSONField(default=dict)


class FormatReviewEvent(models.Model):
    scope = models.ForeignKey(FormatReviewScope, on_delete=models.PROTECT)
    inspection_date = models.DateField(db_index=True)
    action = models.CharField(max_length=16)
    actor = models.CharField(max_length=150)
    reason = models.TextField()
    targets = models.JSONField(default=list)
    previous = models.JSONField(default=dict)
    created_at = models.DateTimeField()
    is_del = models.BooleanField(default=False)
    checked_urls = models.JSONField(default=list)


class FormatReviewCapture(models.Model):
    event = models.ForeignKey(FormatReviewEvent, on_delete=models.PROTECT, related_name='captures')
    name = models.CharField(max_length=150)
    content_type = models.CharField(max_length=30)
    content = models.BinaryField()
