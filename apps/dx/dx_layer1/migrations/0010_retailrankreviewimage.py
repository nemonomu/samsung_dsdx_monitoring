from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('dx_layer1', '0009_column_review_evidence')]

    operations = [migrations.CreateModel(name='RetailRankReviewImage', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('revision', models.PositiveIntegerField()),
        ('name', models.CharField(max_length=200)),
        ('content', models.BinaryField()),
        ('content_type', models.CharField(max_length=32)),
        ('size', models.PositiveIntegerField()),
        ('digest', models.CharField(max_length=64)),
        ('created_at', models.DateTimeField()),
        ('review', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name='images', to='dx_layer1.retailrankreview')),
    ])]
