import pytest
from django.contrib.contenttypes.models import ContentType
from django.template import Context, Template

from dynamic_template.models import DynamicTemplate, DynamicTemplateVariant
from dynamic_template.variant_args import parse_variant_arguments
from tests.app.models import Product


def _create_dt(label, cts, template, **kwargs):
    dt = DynamicTemplate.objects.create(label=label, template=template, **kwargs)
    dt.content_types.set(cts if isinstance(cts, (list, tuple)) else [cts])
    return dt


def test_parse_variant_arguments_bare_flag():
    assert parse_variant_arguments("woman") == {"woman": True}


def test_parse_variant_arguments_key_value():
    assert parse_variant_arguments("woman=true debug=false") == {
        "woman": True,
        "debug": False,
    }


def test_parse_variant_arguments_json():
    assert parse_variant_arguments('{"woman": true, "title": "Hi"}') == {
        "woman": True,
        "title": "Hi",
    }


@pytest.mark.django_db
def test_dyntpl_variant_applies_bare_argument():
    ct = ContentType.objects.get_for_model(Product)
    base = _create_dt(
        "List contact",
        ct,
        "{% if woman %}F{% else %}M{% endif %}",
    )
    DynamicTemplateVariant.objects.create(
        dynamic_template=base,
        label="only woman",
        arguments="woman",
    )

    out = Template("{% load dyntpl %}{% dyntpl list-contact-only-woman %}").render(Context({}))
    assert out.strip() == "F"


@pytest.mark.django_db
def test_dyntpl_variant_equivalent_to_base_with_kwargs():
    ct = ContentType.objects.get_for_model(Product)
    base = _create_dt(
        "List contact",
        ct,
        "{% if woman %}F{% else %}M{% endif %}",
    )
    DynamicTemplateVariant.objects.create(
        dynamic_template=base,
        label="only woman",
        arguments="woman=true",
    )

    variant_out = Template(
        "{% load dyntpl %}{% dyntpl list-contact-only-woman %}",
    ).render(Context({}))
    direct_out = Template(
        "{% load dyntpl %}{% dyntpl list-contact woman %}",
    ).render(Context({}))
    assert variant_out.strip() == direct_out.strip() == "F"


@pytest.mark.django_db
def test_dyntpl_tag_kwargs_override_variant_arguments():
    ct = ContentType.objects.get_for_model(Product)
    base = _create_dt(
        "List contact",
        ct,
        "{% if woman %}F{% else %}M{% endif %}",
    )
    DynamicTemplateVariant.objects.create(
        dynamic_template=base,
        label="only woman",
        arguments="woman",
    )

    out = Template(
        "{% load dyntpl %}{% dyntpl list-contact-only-woman woman=false %}",
    ).render(Context({}))
    assert out.strip() == "M"


@pytest.mark.django_db
def test_variant_rename_updates_named_id():
    ct = ContentType.objects.get_for_model(Product)
    dt = _create_dt(
        "List contact",
        ct,
        "{% if woman %}F{% else %}M{% endif %}",
    )
    variant = DynamicTemplateVariant.objects.create(
        dynamic_template=dt,
        label="only woman",
        arguments="woman",
    )
    assert variant.named_id == "list-contact-only-woman"

    variant.label = "only man"
    variant.save()
    variant.refresh_from_db()
    assert variant.named_id == "list-contact-only-man"


@pytest.mark.django_db
def test_variant_rename_uses_fresh_parent_named_id():
    ct = ContentType.objects.get_for_model(Product)
    dt = _create_dt("List contact", ct, "x")
    variant = DynamicTemplateVariant.objects.create(
        dynamic_template=dt,
        label="only woman",
        arguments="woman",
    )

    dt.label = "Contact list"
    dt.save()
    variant.refresh_from_db()
    assert variant.named_id == "contact-list-only-woman"

    variant.label = "only man"
    variant.dynamic_template = DynamicTemplate(
        pk=dt.pk,
        label="List contact",
        template="x",
        named_id="list-contact",
    )
    variant.save()
    variant.refresh_from_db()
    assert variant.named_id == "contact-list-only-man"


@pytest.mark.django_db
def test_parent_save_resyncs_stale_variant_named_id():
    ct = ContentType.objects.get_for_model(Product)
    dt = _create_dt("List contact", ct, "x")
    variant = DynamicTemplateVariant.objects.create(
        dynamic_template=dt,
        label="only woman",
        arguments="woman",
    )
    DynamicTemplateVariant.objects.filter(pk=variant.pk).update(named_id="only-woman")
    variant.refresh_from_db()
    assert variant.named_id == "only-woman"

    dt.template = "y"
    dt.save()
    variant.refresh_from_db()
    assert variant.named_id == "list-contact-only-woman"


@pytest.mark.django_db
def test_parent_rename_resyncs_variant_named_ids():
    ct = ContentType.objects.get_for_model(Product)
    dt = _create_dt("List contact", ct, "x")
    variant = DynamicTemplateVariant.objects.create(
        dynamic_template=dt,
        label="only woman",
        arguments="woman",
    )
    assert variant.named_id == "list-contact-only-woman"

    dt.label = "Contact list"
    dt.save()
    variant.refresh_from_db()
    assert variant.named_id == "contact-list-only-woman"

    ct = ContentType.objects.get_for_model(Product)
    base = _create_dt(
        "List contact",
        ct,
        "{% if woman %}F{% else %}M{% endif %}",
    )
    DynamicTemplateVariant.objects.create(
        dynamic_template=base,
        label="only woman",
        arguments="woman",
    )

    out = Template(
        "{% load dyntpl %}{% dyntpl list-contact-only-woman woman=false %}",
    ).render(Context({}))
    assert out.strip() == "M"
