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
