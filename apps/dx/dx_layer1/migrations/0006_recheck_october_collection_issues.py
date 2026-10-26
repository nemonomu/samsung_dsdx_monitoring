from django.db import migrations


def reset_coverage(apps, schema_editor):
    # Re-evaluate October with MAIN/BSR and batch policies. Keep every audit event.
    apps.get_model('dx_layer1', 'CollectionIssueScan').objects.using(
        schema_editor.connection.alias).update(scanned_through=None, last_checked_at=None)


class Migration(migrations.Migration):
    dependencies = [('dx_layer1', '0005_columnchecklink')]
    operations = [migrations.RunPython(reset_coverage, migrations.RunPython.noop)]
