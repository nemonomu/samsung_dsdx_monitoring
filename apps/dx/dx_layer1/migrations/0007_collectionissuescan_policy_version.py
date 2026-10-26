from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('dx_layer1', '0006_recheck_october_collection_issues')]
    operations = [migrations.AddField(
        model_name='collectionissuescan', name='policy_version',
        field=models.PositiveIntegerField(default=0),
    )]
