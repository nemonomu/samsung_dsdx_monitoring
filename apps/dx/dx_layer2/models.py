from django.db import models


class AdminValidationReviewCheck(models.Model):
    """Administrator acknowledgement only; never changes validation decisions."""

    environment = models.CharField(max_length=10)
    inspection_date = models.DateField()
    kind = models.CharField(max_length=20)
    table_name = models.CharField(max_length=200)
    retailer = models.CharField(max_length=200)
    checked = models.BooleanField(default=False)
    actor = models.CharField(max_length=150)
    updated_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['environment', 'inspection_date', 'kind', 'table_name', 'retailer'],
            name='unique_admin_validation_check',
        )]


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
