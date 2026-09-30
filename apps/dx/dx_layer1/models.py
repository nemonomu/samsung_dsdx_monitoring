from django.db import models


class CollectionDailySnapshot(models.Model):
    country = models.CharField(max_length=4)
    inspection_date = models.DateField()
    source_date = models.DateField()
    rows = models.JSONField(default=list)
    digest = models.CharField(max_length=64)
    refresh_error = models.BooleanField(default=False)
    updated_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['country', 'inspection_date'], name='collection_daily_unique')]
        indexes = [models.Index(fields=['country', 'source_date'], name='collection_daily_source')]


class CollectionWeeklySnapshot(models.Model):
    country = models.CharField(max_length=4)
    week_start = models.DateField()
    rows = models.JSONField(default=list)
    updated_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['country', 'week_start'], name='collection_week_unique')]


class CollectionStatisticsLease(models.Model):
    name = models.CharField(max_length=40, primary_key=True)
    owner = models.CharField(max_length=36)
    expires_at = models.DateTimeField()


class RetailNormalReview(models.Model):
    """Manual decisions are separate from automatic collection results."""

    fingerprint = models.CharField(max_length=64, unique=True)
    inspection_date = models.DateField(db_index=True)
    context = models.JSONField()
    active = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=0)
    history = models.JSONField(default=list)
