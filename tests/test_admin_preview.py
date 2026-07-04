"""Tests for admin preview helpers."""

import pytest
from django.contrib.contenttypes.models import ContentType

from dynamic_template.admin.template import _render_content_type_previews
from dynamic_template.models import DynamicTemplate, DynamicTemplateVariant
from tests.app.models import Product


def _create_dt(label, cts, template, **kwargs):
    dt = DynamicTemplate.objects.create(label=label, template=template, **kwargs)
    dt.content_types.set(cts if isinstance(cts, (list, tuple)) else [cts])
    return dt


@pytest.mark.django_db
def test_preview_by_content_type_includes_variant_sub_previews():
    ct = ContentType.objects.get_for_model(Product)
    dt = _create_dt(
        "List contact",
        ct,
        "{% if woman %}F{% else %}M{% endif %}",
    )
    DynamicTemplateVariant.objects.create(
        dynamic_template=dt,
        label="only woman",
        arguments="woman",
    )
    Product.objects.create(name="Alice")
    dt = DynamicTemplate.objects.prefetch_related("content_types", "variants").get(pk=dt.pk)

    previews = _render_content_type_previews(dt, request=None, extra={})
    assert len(previews) == 1
    preview = previews[0]
    assert preview["error"] is None
    assert preview["html"].strip() == "M"
    assert len(preview["variants"]) == 1
    variant_preview = preview["variants"][0]
    assert variant_preview["named_id"] == "list-contact-only-woman"
    assert variant_preview["html"].strip() == "F"
    assert variant_preview["error"] is None


@pytest.mark.django_db
def test_preview_by_content_type_merges_form_extra_over_variant():
    ct = ContentType.objects.get_for_model(Product)
    dt = _create_dt(
        "List contact",
        ct,
        "{% if woman %}F{% else %}M{% endif %}",
    )
    DynamicTemplateVariant.objects.create(
        dynamic_template=dt,
        label="only woman",
        arguments="woman",
    )
    Product.objects.create(name="Alice")
    dt = DynamicTemplate.objects.prefetch_related("content_types", "variants").get(pk=dt.pk)

    previews = _render_content_type_previews(dt, request=None, extra={"woman": False})
    assert previews[0]["html"].strip() == "M"
    assert previews[0]["variants"][0]["html"].strip() == "M"
