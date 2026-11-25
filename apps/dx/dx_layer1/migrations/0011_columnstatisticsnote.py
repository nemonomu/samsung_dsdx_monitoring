from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('dx_layer1', '0010_retailrankreviewimage')]

    operations = [migrations.CreateModel(
        name='ColumnStatisticsNote',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('environment', models.CharField(max_length=10)),
            ('country', models.CharField(max_length=4)),
            ('product', models.CharField(max_length=12)),
            ('retailer', models.CharField(max_length=80)),
            ('column', models.CharField(max_length=120)),
            ('text', models.TextField(blank=True, max_length=2000)),
            ('revision', models.PositiveIntegerField(default=1)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
        ],
        options={'constraints': [models.UniqueConstraint(
            fields=('environment', 'country', 'product', 'retailer', 'column'),
            name='column_statistics_note_unique')]},
    )]
