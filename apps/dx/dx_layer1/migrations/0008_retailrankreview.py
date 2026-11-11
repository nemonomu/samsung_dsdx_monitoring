from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('dx_layer1', '0007_collectionissuescan_policy_version')]
    operations = [migrations.CreateModel(
        name='RetailRankReview',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('fingerprint', models.CharField(max_length=64, unique=True)),
            ('environment', models.CharField(max_length=10)),
            ('source_date', models.DateField(db_index=True)),
            ('context', models.JSONField()),
            ('result', models.CharField(default='미확인', max_length=40)),
            ('memo', models.TextField(blank=True)),
            ('revision', models.PositiveIntegerField(default=0)),
            ('updated_by', models.CharField(max_length=150)),
            ('updated_at', models.DateTimeField()),
            ('history', models.JSONField(default=list)),
        ],
    )]
