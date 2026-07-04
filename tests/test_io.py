"""Tests for dynamic_template.io (export / import round-trip, raw_object, context_object)."""

import io
import json
import zipfile

import pytest
from django.contrib.contenttypes.models import ContentType
from django.template import Context, Template

from dynamic_template.io import (
    archive_attachment_response,
    build_export_archive,
    content_disposition_attachment,
    import_payload,
    json_attachment_response,
    serialize_export,
)
from dynamic_template.models import DynamicRelationContext, DynamicTemplate, DynamicTemplateVariant
from tests.app.models import Article, Product


def _create_dt(label, cts, template, **kwargs):
    dt = DynamicTemplate.objects.create(label=label, template=template, **kwargs)
    dt.content_types.set(cts if isinstance(cts, (list, tuple)) else [cts])
    return dt


# ---------------------------------------------------------------------------
# content_disposition_attachment
# ---------------------------------------------------------------------------


def test_content_disposition_ascii():
    assert content_disposition_attachment("foo.json") == 'attachment; filename="foo.json"'


def test_content_disposition_non_ascii():
    header = content_disposition_attachment("café.json")
    assert "filename*=UTF-8''" in header
    assert "caf" in header


# ---------------------------------------------------------------------------
# json_attachment_response
# ---------------------------------------------------------------------------


def test_json_attachment_response():
    resp = json_attachment_response("test.json", {"a": 1})
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/json; charset=utf-8"
    assert "attachment" in resp["Content-Disposition"]
    body = json.loads(resp.content)
    assert body == {"a": 1}


def test_archive_attachment_response():
    resp = archive_attachment_response("templates.zip", b"PK\x03\x04")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/zip"
    assert "attachment" in resp["Content-Disposition"]


# ---------------------------------------------------------------------------
# export archive (one JSON per template)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_build_export_archive_one_json_per_named_id():
    ct_product = ContentType.objects.get_for_model(Product)
    ct_article = ContentType.objects.get_for_model(Article)
    dt_a = _create_dt("Archive A", ct_product, "A")
    _create_dt("Archive B", ct_product, "B")
    DynamicRelationContext.objects.create(
        dynamic_template=dt_a,
        content_type=ct_article,
        manager_method="objects.all",
        name="articles",
    )

    archive = build_export_archive(DynamicTemplate.objects.all())
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        names = sorted(zf.namelist())
        assert names == ["archive-a.json", "archive-b.json"]
        payload_a = json.loads(zf.read("archive-a.json").decode("utf-8"))
        assert payload_a["format_version"] == 2
        assert len(payload_a["dynamic_templates"]) == 1
        assert payload_a["dynamic_templates"][0]["label"] == "Archive A"
        assert payload_a["dynamic_templates"][0]["relation_contexts"][0]["name"] == "articles"


@pytest.mark.django_db
def test_archive_json_files_are_importable():
    ct = ContentType.objects.get_for_model(Product)
    _create_dt("Zip import", ct, "hello")
    archive = build_export_archive(DynamicTemplate.objects.all())

    DynamicTemplate.objects.all().delete()

    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for name in zf.namelist():
            payload = json.loads(zf.read(name).decode("utf-8"))
            result = import_payload(payload)
            assert result["errors"] == []

    dt = DynamicTemplate.objects.get()
    assert dt.label == "Zip import"
    assert dt.template == "hello"


# ---------------------------------------------------------------------------
# serialize / export round-trip
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_export_contains_raw_object_and_context_object():
    ct = ContentType.objects.get_for_model(Product)
    _create_dt("Export test", ct, "Hello", raw_object=True, context_object="product")
    payload = serialize_export(DynamicTemplate.objects.all())
    tpl_data = payload["dynamic_templates"][0]
    assert tpl_data["raw_object"] is True
    assert tpl_data["context_object"] == "product"
    assert f"{ct.app_label}.{ct.model}" in tpl_data["content_types"]


@pytest.mark.django_db
def test_export_includes_relation_contexts():
    ct_product = ContentType.objects.get_for_model(Product)
    ct_article = ContentType.objects.get_for_model(Article)
    dt = _create_dt("With rels", ct_product, "x")
    DynamicRelationContext.objects.create(
        dynamic_template=dt,
        content_type=ct_article,
        manager_method="objects.all",
        filter_spec={"product_id": "pk"},
        name="articles",
    )
    payload = serialize_export(DynamicTemplate.objects.all())
    rels = payload["dynamic_templates"][0]["relation_contexts"]
    assert len(rels) == 1
    assert rels[0]["name"] == "articles"
    assert rels[0]["filter_spec"] == {"product_id": "pk"}


# ---------------------------------------------------------------------------
# import_payload – legacy single content_type key (backward compat)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_import_creates_template_legacy_content_type():
    ct = ContentType.objects.get_for_model(Product)
    data = {
        "format_version": 1,
        "dynamic_templates": [
            {
                "label": "Imported",
                "content_type": f"{ct.app_label}.{ct.model}",
                "template": "{{ object.name }}",
                "model_fields": ["name"],
                "raw_object": True,
                "context_object": "product",
            }
        ],
    }
    result = import_payload(data)
    assert result["created"] == 1
    assert result["updated"] == 0
    assert result["errors"] == []
    dt = DynamicTemplate.objects.get()
    assert dt.label == "Imported"
    assert dt.raw_object is True
    assert dt.context_object == "product"
    assert dt.model_fields == ["name"]
    assert dt.content_types.filter(pk=ct.pk).exists()


@pytest.mark.django_db
def test_import_creates_template_content_types_list():
    ct_product = ContentType.objects.get_for_model(Product)
    ct_article = ContentType.objects.get_for_model(Article)
    data = {
        "format_version": 1,
        "dynamic_templates": [
            {
                "label": "Multi CT",
                "content_types": [
                    f"{ct_product.app_label}.{ct_product.model}",
                    f"{ct_article.app_label}.{ct_article.model}",
                ],
                "template": "hello",
            }
        ],
    }
    result = import_payload(data)
    assert result["created"] == 1
    assert result["errors"] == []
    dt = DynamicTemplate.objects.get()
    assert dt.content_types.count() == 2


@pytest.mark.django_db
def test_import_updates_existing_template():
    ct = ContentType.objects.get_for_model(Product)
    _create_dt("Updatable", ct, "old")
    data = {
        "format_version": 1,
        "dynamic_templates": [
            {
                "label": "Updatable",
                "content_type": f"{ct.app_label}.{ct.model}",
                "template": "new",
                "raw_object": True,
                "context_object": "obj",
            }
        ],
    }
    result = import_payload(data, replace=True)
    assert result["created"] == 0
    assert result["updated"] == 1
    dt = DynamicTemplate.objects.get()
    assert dt.template == "new"
    assert dt.raw_object is True
    assert dt.context_object == "obj"


@pytest.mark.django_db
def test_import_no_replace_skips_existing():
    ct = ContentType.objects.get_for_model(Product)
    _create_dt("Keep", ct, "original")
    data = {
        "format_version": 1,
        "dynamic_templates": [
            {
                "label": "Keep",
                "content_type": f"{ct.app_label}.{ct.model}",
                "template": "replaced",
            }
        ],
    }
    result = import_payload(data, replace=False)
    assert result["created"] == 0
    assert result["updated"] == 0
    assert DynamicTemplate.objects.get().template == "original"


@pytest.mark.django_db
def test_import_with_relation_contexts():
    ct_product = ContentType.objects.get_for_model(Product)
    ct_article = ContentType.objects.get_for_model(Article)
    data = {
        "format_version": 1,
        "dynamic_templates": [
            {
                "label": "With rel",
                "content_type": f"{ct_product.app_label}.{ct_product.model}",
                "template": "x",
                "relation_contexts": [
                    {
                        "content_type": f"{ct_article.app_label}.{ct_article.model}",
                        "manager_method": "objects.all",
                        "filter_spec": {"product_id": "pk"},
                        "name": "articles",
                    }
                ],
            }
        ],
    }
    result = import_payload(data)
    assert result["created"] == 1
    assert result["errors"] == []
    assert DynamicRelationContext.objects.count() == 1
    rc = DynamicRelationContext.objects.get()
    assert rc.name == "articles"
    assert rc.filter_spec == {"product_id": "pk"}


@pytest.mark.django_db
def test_import_reports_errors_for_bad_items():
    data = {
        "format_version": 1,
        "dynamic_templates": [
            {"label": "", "content_type": "app.product"},
            "not-a-dict",
        ],
    }
    result = import_payload(data)
    assert result["created"] == 0
    assert len(result["errors"]) == 2


@pytest.mark.django_db
def test_import_rejects_bad_format_version():
    with pytest.raises(ValueError, match="format_version"):
        import_payload({"format_version": 99, "dynamic_templates": []})


@pytest.mark.django_db
def test_export_import_round_trip():
    """Full export → import round-trip preserves all fields."""
    ct_product = ContentType.objects.get_for_model(Product)
    ct_article = ContentType.objects.get_for_model(Article)
    dt = _create_dt(
        "Round trip",
        ct_product,
        "{{ object.name }}",
        model_fields=["name"],
        annotate_fields=["n_art"],
        fields=["toto"],
        raw_object=True,
        context_object="product",
    )
    DynamicRelationContext.objects.create(
        dynamic_template=dt,
        content_type=ct_article,
        manager_method="objects.all",
        filter_spec={"product_id": "pk"},
        filter_literal={"title": "x"},
        model_fields=["title"],
        annotate_fields=[],
        fields=["title_upper"],
        name="articles",
    )
    payload = serialize_export(DynamicTemplate.objects.all())

    DynamicRelationContext.objects.all().delete()
    DynamicTemplate.objects.all().delete()

    result = import_payload(payload)
    assert result["created"] == 1
    assert result["errors"] == []

    dt2 = DynamicTemplate.objects.get()
    assert dt2.label == "Round trip"
    assert dt2.model_fields == ["name"]
    assert dt2.annotate_fields == ["n_art"]
    assert dt2.fields == ["toto"]
    assert dt2.raw_object is True
    assert dt2.context_object == "product"
    assert dt2.content_types.filter(pk=ct_product.pk).exists()

    rc = DynamicRelationContext.objects.get()
    assert rc.name == "articles"
    assert rc.manager_method == "objects.all"
    assert rc.filter_spec == {"product_id": "pk"}
    assert rc.filter_literal == {"title": "x"}
    assert rc.model_fields == ["title"]
    assert rc.fields == ["title_upper"]


@pytest.mark.django_db
def test_export_import_round_trip_variants():
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
    payload = serialize_export(DynamicTemplate.objects.all())
    tpl_data = payload["dynamic_templates"][0]
    assert len(tpl_data["variants"]) == 1
    assert tpl_data["variants"][0]["label"] == "only woman"
    assert tpl_data["variants"][0]["arguments"] == "woman"
    assert tpl_data["variants"][0]["named_id"] == "list-contact-only-woman"

    DynamicTemplateVariant.objects.all().delete()
    DynamicTemplate.objects.all().delete()

    result = import_payload(payload)
    assert result["created"] == 1
    assert result["errors"] == []

    dt2 = DynamicTemplate.objects.get()
    variant = dt2.variants.get()
    assert variant.label == "only woman"
    assert variant.named_id == "list-contact-only-woman"
    assert variant.arguments == "woman"


@pytest.mark.django_db
def test_import_creates_variants_from_payload():
    ct = ContentType.objects.get_for_model(Product)
    data = {
        "format_version": 2,
        "dynamic_templates": [
            {
                "label": "List contact",
                "content_types": [f"{ct.app_label}.{ct.model}"],
                "template": "{% if woman %}F{% else %}M{% endif %}",
                "variants": [
                    {"label": "only woman", "arguments": "woman=true"},
                ],
            }
        ],
    }
    result = import_payload(data)
    assert result["created"] == 1
    assert result["errors"] == []

    dt = DynamicTemplate.objects.get()
    variant = dt.variants.get()
    assert variant.named_id == "list-contact-only-woman"
    assert variant.arguments == "woman=true"


@pytest.mark.django_db
def test_import_replace_clears_old_variants():
    ct = ContentType.objects.get_for_model(Product)
    dt = _create_dt("List contact", ct, "x")
    DynamicTemplateVariant.objects.create(
        dynamic_template=dt,
        label="old",
        arguments="old",
    )
    data = {
        "format_version": 2,
        "dynamic_templates": [
            {
                "label": "List contact",
                "content_types": [f"{ct.app_label}.{ct.model}"],
                "template": "y",
                "variants": [
                    {"label": "new", "arguments": "new"},
                ],
            }
        ],
    }
    result = import_payload(data, replace=True)
    assert result["updated"] == 1
    assert dt.variants.count() == 1
    assert dt.variants.get().label == "new"


# ---------------------------------------------------------------------------
# raw_object behaviour
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_raw_object_exposes_model_instance():
    ct = ContentType.objects.get_for_model(Product)
    dt = _create_dt("Raw", ct, "{{ object.name }}", raw_object=True)
    product = Product.objects.create(name="RawProd")

    out = Template(
        "{% load dyntpl %}{% dyntpl nid obj=p %}",
    ).render(Context({"nid": dt.named_id, "p": product}))
    assert out.strip() == "RawProd"


@pytest.mark.django_db
def test_raw_object_false_gives_dict():
    """With raw_object=False and model_fields set, object is a dict."""
    ct = ContentType.objects.get_for_model(Product)
    dt = _create_dt("Dict obj", ct, "{{ object.name }}", model_fields=["name"], raw_object=False)
    product = Product.objects.create(name="DictProd")

    out = Template(
        "{% load dyntpl %}{% dyntpl nid obj=p %}",
    ).render(Context({"nid": dt.named_id, "p": product}))
    assert out.strip() == "DictProd"


# ---------------------------------------------------------------------------
# context_object behaviour
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_context_object_resolves_from_parent_context():
    ct = ContentType.objects.get_for_model(Product)
    dt = _create_dt(
        "Auto obj", ct, "{{ object.name }}", model_fields=["name"], context_object="product"
    )
    product = Product.objects.create(name="AutoProd")

    out = Template(
        "{% load dyntpl %}{% dyntpl nid %}",
    ).render(Context({"nid": dt.named_id, "product": product}))
    assert out.strip() == "AutoProd"


@pytest.mark.django_db
def test_context_object_dotted_path():
    ct = ContentType.objects.get_for_model(Product)
    dt = _create_dt(
        "Dotted obj",
        ct,
        "{{ object.name }}",
        model_fields=["name"],
        context_object="article.product",
    )
    product = Product.objects.create(name="Dotted")
    article = Article.objects.create(title="Art", product=product)

    out = Template(
        "{% load dyntpl %}{% dyntpl nid %}",
    ).render(Context({"nid": dt.named_id, "article": article}))
    assert out.strip() == "Dotted"
