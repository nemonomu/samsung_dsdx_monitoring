from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('dx_layer1', '0004_collectionissuescan_coverage_start_and_more')]
    operations = [migrations.CreateModel(
        name='ColumnCheckLink',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('environment', models.CharField(max_length=10)),
            ('country', models.CharField(max_length=4)),
            ('product', models.CharField(max_length=12)),
            ('retailer', models.CharField(max_length=80)),
            ('column', models.CharField(blank=True, max_length=120)),
            ('url', models.URLField(max_length=4000)),
            ('revision', models.PositiveIntegerField(default=1)),
            ('updated_by', models.CharField(max_length=150)),
            ('updated_at', models.DateTimeField()),
            ('history', models.JSONField(default=list)),
        ],
        options={'constraints': [models.UniqueConstraint(
            fields=('environment', 'country', 'product', 'retailer', 'column'),
            name='column_check_link_unique')]},
    )]
