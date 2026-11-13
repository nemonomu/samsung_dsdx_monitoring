from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('dx_layer1', '0008_retailrankreview')]
    operations = [
        migrations.CreateModel(name='ColumnNormalReview', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('fingerprint', models.CharField(max_length=64, unique=True)),
            ('environment', models.CharField(max_length=10)),
            ('source_date', models.DateField(db_index=True)),
            ('context', models.JSONField()),
            ('active', models.BooleanField(default=False)),
            ('revision', models.PositiveIntegerField(default=0)),
            ('history', models.JSONField(default=list)),
        ]),
        migrations.CreateModel(name='ColumnReviewImage', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('revision', models.PositiveIntegerField()),
            ('content', models.BinaryField()),
            ('content_type', models.CharField(max_length=32)),
            ('digest', models.CharField(max_length=64)),
            ('created_at', models.DateTimeField()),
            ('review', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                        related_name='images', to='dx_layer1.columnnormalreview')),
        ]),
    ]
