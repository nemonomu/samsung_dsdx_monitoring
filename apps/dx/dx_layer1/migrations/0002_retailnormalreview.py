from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('dx_layer1', '0001_collection_statistics')]
    operations = [
        migrations.CreateModel(
            name='RetailNormalReview',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fingerprint', models.CharField(max_length=64, unique=True)),
                ('inspection_date', models.DateField(db_index=True)),
                ('context', models.JSONField()),
                ('active', models.BooleanField(default=False)),
                ('revision', models.PositiveIntegerField(default=0)),
                ('history', models.JSONField(default=list)),
            ],
        ),
    ]
