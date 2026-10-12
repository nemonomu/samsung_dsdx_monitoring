from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(name='FormatReviewScope', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('fingerprint', models.CharField(max_length=64, unique=True)),
            ('context', models.JSONField()),
            ('revision', models.PositiveIntegerField(default=0)),
            ('policies', models.JSONField(default=dict)),
        ]),
        migrations.CreateModel(name='FormatReviewEvent', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('inspection_date', models.DateField(db_index=True)),
            ('action', models.CharField(max_length=16)),
            ('actor', models.CharField(max_length=150)),
            ('reason', models.TextField()),
            ('targets', models.JSONField(default=list)),
            ('previous', models.JSONField(default=dict)),
            ('created_at', models.DateTimeField()),
            ('is_del', models.BooleanField(default=False)),
            ('scope', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='dx_layer2.formatreviewscope')),
        ]),
    ]
