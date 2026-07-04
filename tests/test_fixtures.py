"""Tests for dynamic_template.fixtures discovery and loading."""

import pytest
from django.contrib.contenttypes.models import ContentType

from dynamic_template.fixtures import (
    discover_dyntpl_fixture_files,
    load_dyntpl_fixtures,
    normalize_fixture_payload,
)
from dynamic_template.models import DynamicTemplate
from dynamic_template.rendering import render_dynamic_template_fragment
from tests.app.models import Product


@pytest.mark.django_db
def test_discover_dyntpl_fixture_files_in_installed_apps():
    files = discover_dyntpl_fixture_files(app_labels=["app"])
    paths = [f.relative_path for f in files]
    assert "dyntpl/product-greeting.json" in paths
    assert "dyntpl/product-nested-child.json" in paths
    assert "dyntpl/product-nested-parent.json" in paths
    assert "dyntpl/product-dates.json" in paths
    assert "dyntpl/product-contact-list.json" in paths


@pytest.mark.django_db
def test_normalize_fixture_payload_single_template():
    payload = normalize_fixture_payload(
        {"label": "X", "content_types": ["app.product"], "template": "x"}
    )
    assert len(payload["dynamic_templates"]) == 1
    assert payload["dynamic_templates"][0]["label"] == "X"


@pytest.mark.django_db
def test_load_dyntpl_fixtures_creates_template():
    result = load_dyntpl_fixtures(replace=True, app_labels=["app"])
    assert result.files_loaded >= 1
    assert result.errors == []
    assert result.created >= 1

    dt = DynamicTemplate.objects.get(label="Fixture greeting")
    assert dt.template == "Hello {{ object.name }}"

    product = Product.objects.create(name="FromFixture")
    html = render_dynamic_template_fragment(dt, bound=product)
    assert html.strip() == "Hello FromFixture"


@pytest.mark.django_db
def test_load_dyntpl_fixtures_replaces_existing():
    ct = ContentType.objects.get_for_model(Product)
    dt = DynamicTemplate.objects.create(label="Fixture greeting", template="old")
    dt.content_types.set([ct])

    result = load_dyntpl_fixtures(replace=True, app_labels=["app"])
    assert result.updated >= 1
    assert DynamicTemplate.objects.get(label="Fixture greeting").template != "old"


@pytest.mark.django_db
def test_load_dyntpl_fixtures_no_replace_skips_existing():
    ct = ContentType.objects.get_for_model(Product)
    dt = DynamicTemplate.objects.create(label="Fixture greeting", template="keep")
    dt.content_types.set([ct])

    result = load_dyntpl_fixtures(replace=False, app_labels=["app"])
    assert result.updated == 0
    assert DynamicTemplate.objects.get(label="Fixture greeting").template == "keep"


@pytest.mark.django_db
def test_fixture_nested_parent_calls_child_without_load():
    load_dyntpl_fixtures(replace=True, app_labels=["app"])
    parent = DynamicTemplate.objects.get(label="Fixture nested parent")
    product = Product.objects.create(name="Nested")
    html = render_dynamic_template_fragment(parent, bound=product)
    assert html.strip() == "Start [Nested] End"


@pytest.mark.django_db
def test_fixture_dates_uses_timezone_without_load():
    import re

    load_dyntpl_fixtures(replace=True, app_labels=["app"])
    dates_tpl = DynamicTemplate.objects.get(label="Fixture dates")
    html = render_dynamic_template_fragment(dates_tpl)
    assert re.fullmatch(r"Date: \d{4}-\d{2}-\d{2}", html.strip())


@pytest.mark.django_db
def test_fixture_loads_variants_with_template():
    from django.template import Context, Template

    load_dyntpl_fixtures(replace=True, app_labels=["app"])
    dt = DynamicTemplate.objects.get(label="Fixture contact list")
    assert dt.variants.count() == 1
    variant = dt.variants.get()
    assert variant.named_id == "fixture-contact-list-only-woman"

    out = Template("{% load dyntpl %}{% dyntpl fixture-contact-list-only-woman %}").render(
        Context({})
    )
    assert out.strip() == "F"
