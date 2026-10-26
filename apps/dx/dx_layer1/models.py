from django.db import models


class ColumnCheckLink(models.Model):
    environment = models.CharField(max_length=10)
    country = models.CharField(max_length=4)
    product = models.CharField(max_length=12)
    retailer = models.CharField(max_length=80)
    column = models.CharField(max_length=120, blank=True)
    url = models.URLField(max_length=4000)
    revision = models.PositiveIntegerField(default=1)
    updated_by = models.CharField(max_length=150)
    updated_at = models.DateTimeField()
    history = models.JSONField(default=list)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['environment', 'country', 'product', 'retailer', 'column'],
            name='column_check_link_unique')]


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


class CollectionIssue(models.Model):
    """An original source-day incident; later dates never replace its evidence."""
    environment = models.CharField(max_length=10)
    country = models.CharField(max_length=4)
    product = models.CharField(max_length=12)
    retailer = models.CharField(max_length=80)
    source_date = models.DateField()
    column = models.CharField(max_length=120, blank=True)  # empty = whole collection
    severity = models.CharField(max_length=20)
    status = models.CharField(max_length=12, default='open')
    baseline = models.FloatField(null=True)
    observed_count = models.PositiveIntegerField()
    current_count = models.PositiveIntegerField()
    evidence = models.JSONField(default=dict)
    first_detected_at = models.DateTimeField()
    last_checked_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True)
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['environment', 'country', 'product', 'retailer', 'source_date', 'column'],
            name='collection_issue_unique')]
        indexes = [models.Index(fields=['environment', 'status', 'source_date'], name='collection_issue_open')]


class CollectionIssueEvent(models.Model):
    issue = models.ForeignKey(CollectionIssue, on_delete=models.CASCADE, related_name='events')
    action = models.CharField(max_length=20)
    username = models.CharField(max_length=150, blank=True)
    reason = models.TextField(blank=True)
    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField()


class CollectionIssueScan(models.Model):
    environment = models.CharField(max_length=10)
    country = models.CharField(max_length=4)
    product = models.CharField(max_length=12)
    retailer = models.CharField(max_length=80)
    coverage_start = models.DateField(null=True)
    start_basis = models.CharField(max_length=20, blank=True)
    scanned_through = models.DateField(null=True)
    last_checked_at = models.DateTimeField(null=True)
    error = models.BooleanField(default=False)
    policy_version = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['environment', 'country', 'product', 'retailer'], name='collection_issue_scan_unique')]
