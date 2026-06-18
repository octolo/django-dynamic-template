"""
Migrate DynamicTemplate.content_type (FK) → content_types (M2M).

Steps:
1. Add the new M2M field (creates the junction table).
2. Copy each row's content_type_id into the M2M relation.
3. Drop the old index that referenced the FK column.
4. Remove the FK column.
5. Flip named_id to a simple global unique constraint.
"""

import namedid.fields
from django.db import migrations, models


def _copy_fk_to_m2m(apps, schema_editor):
    DynamicTemplate = apps.get_model("dynamic_template", "DynamicTemplate")
    for dt in DynamicTemplate.objects.select_related("content_type").iterator():
        if dt.content_type_id is not None:
            dt.content_types.add(dt.content_type_id)


class Migration(migrations.Migration):

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("dynamic_template", "0001_initial"),
    ]

    operations = [
        # 1. Add the M2M junction table.
        migrations.AddField(
            model_name="dynamictemplate",
            name="content_types",
            field=models.ManyToManyField(
                blank=True,
                related_name="dynamic_templates",
                to="contenttypes.contenttype",
                verbose_name="content types",
            ),
        ),
        # 2. Copy existing FK data into the M2M relation.
        migrations.RunPython(_copy_fk_to_m2m, migrations.RunPython.noop),
        # 3. Drop the old composite index on (content_type_id, named_id).
        migrations.RemoveIndex(
            model_name="dynamictemplate",
            name="dynamic_tem_content_426dd1_idx",
        ),
        # 4. Drop the FK column.
        migrations.RemoveField(
            model_name="dynamictemplate",
            name="content_type",
        ),
        # 5. Switch named_id to a simple globally-unique constraint.
        migrations.AlterField(
            model_name="dynamictemplate",
            name="named_id",
            field=namedid.fields.NamedIDField(
                blank=False,
                max_length=255,
                null=False,
                source_fields=["label"],
                unique=True,
            ),
        ),
    ]
