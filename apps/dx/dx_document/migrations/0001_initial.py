from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name='ManualRevision',
            fields=[
                ('version', models.PositiveIntegerField(primary_key=True, serialize=False)),
                ('data', models.JSONField()),
                ('created_by', models.CharField(max_length=150)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['-version']},
        ),
        migrations.CreateModel(
            name='ManualImage',
            fields=[
                ('digest', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('content', models.BinaryField()),
                ('content_type', models.CharField(max_length=32)),
                ('created_by', models.CharField(max_length=150)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
