import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.template import Context, Template

from dynamic_template.models import DynamicTemplate
from tests.app.models import Article, Product

User = get_user_model()


def _create_dt(label, cts, template, **kwargs):
    dt = DynamicTemplate.objects.create(label=label, template=template, **kwargs)
    dt.content_types.set(cts if isinstance(cts, (list, tuple)) else [cts])
    return dt


@pytest.mark.django_db
def test_dyntpl_renders_by_named_id():
    ct = ContentType.objects.get_for_model(User)
    dt = _create_dt("Hello Block", ct, "Hello {{ name }}")
    assert dt.named_id == "hello-block"

    out = Template(
        "{% load dyntpl %}{% dyntpl tpl_id name=user.username %}",
    ).render(Context({"tpl_id": dt.named_id, "user": User(username="Ada")}))

    assert out.strip() == "Hello Ada"


@pytest.mark.django_db
def test_dyntpl_obj_skips_wrong_content_type():
    ct_user = ContentType.objects.get_for_model(User)
    dt = _create_dt("Only users", ct_user, "OK")

    class Other:
        pass

    other = Other()
    out = Template(
        "{% load dyntpl %}{% dyntpl nid obj=o %}",
    ).render(Context({"nid": dt.named_id, "o": other}))

    assert out.strip() == ""


@pytest.mark.django_db
def test_dyntpl_obj_renders_when_content_type_matches():
    ct = ContentType.objects.get_for_model(User)
    dt = _create_dt("Greet", ct, "Hi {{ object.username }}", model_fields=["username"])
    user = User(username="bob")

    out = Template(
        "{% load dyntpl %}{% dyntpl nid obj=u %}",
    ).render(Context({"nid": dt.named_id, "u": user}))

    assert out.strip() == "Hi bob"


@pytest.mark.django_db
def test_dyntpl_ctype_filters_by_content_type():
    """A template with multiple content_types is found when filtering by either one."""
    ct_user = ContentType.objects.get_for_model(User)
    ct_product = ContentType.objects.get_for_model(Product)
    dt = _create_dt("Multi", [ct_user, ct_product], "SHARED")

    out_user = Template(
        "{% load dyntpl %}{% dyntpl nid ctype=user_model %}",
    ).render(Context({"nid": dt.named_id, "user_model": User}))
    assert out_user.strip() == "SHARED"

    out_product = Template(
        "{% load dyntpl %}{% dyntpl nid ctype=product_model %}",
    ).render(Context({"nid": dt.named_id, "product_model": Product}))
    assert out_product.strip() == "SHARED"


@pytest.mark.django_db
def test_dyntpl_obj_empty_model_fields_is_dict_of_all_concrete():
    """``model_fields`` empty → dict of all concrete columns (``{{ object.name }}``)."""
    ct = ContentType.objects.get_for_model(Product)
    dt = _create_dt("Prod tuple", ct, "{{ object.name }}")
    product = Product.objects.create(name="TupleName")

    out = Template(
        "{% load dyntpl %}{% dyntpl nid obj=p %}",
    ).render(Context({"nid": dt.named_id, "p": product}))

    assert out.strip() == "TupleName"


@pytest.mark.django_db
def test_dyntpl_obj_merges_model_fields_annotate_and_class_attr():
    ct = ContentType.objects.get_for_model(Product)
    dt = _create_dt(
        "Merge attrs",
        ct,
        "{{ object.name }}-{{ object.toto }}-{{ object.n_art }}",
        model_fields=["name"],
        annotate_fields=["n_art"],
        fields=["toto"],
    )
    product = Product.objects.create(name="M")
    Article.objects.create(title="x", product=product)
    p = Product.objects.with_n_art().get(pk=product.pk)

    out = Template(
        "{% load dyntpl %}{% dyntpl nid obj=p %}",
    ).render(Context({"nid": dt.named_id, "p": p}))

    assert out.strip() == "M-2-1"


@pytest.mark.django_db
def test_dyntpl_ctype_string_app_label_model():
    ct = ContentType.objects.get_for_model(Product)
    dt = _create_dt("Sku", ct, "ok")
    out = Template(
        '{% load dyntpl %}{% dyntpl nid ctype="app.Product" %}',
    ).render(Context({"nid": dt.named_id}))
    assert out.strip() == "ok"


@pytest.mark.django_db
def test_dyntpl_ctype_not_leaked_into_inner_context():
    ct = ContentType.objects.get_for_model(User)
    dt = _create_dt("Inner", ct, "{{ ctype|default:'none' }}")
    out = Template(
        "{% load dyntpl %}{% dyntpl nid ctype=user_model %}",
    ).render(Context({"nid": dt.named_id, "user_model": User}))
    assert out.strip() == "none"
