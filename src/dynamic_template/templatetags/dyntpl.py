from __future__ import annotations

import json
import logging
from typing import Any

from django import template
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.safestring import mark_safe

from dynamic_template.models import DynamicTemplate, DynamicTemplateVariant
from dynamic_template.rendering import render_dynamic_template_fragment
from dynamic_template.variant_args import parse_variant_arguments

logger = logging.getLogger(__name__)

register = template.Library()


def _resolve_ctype_kwarg(ctype_arg: Any) -> ContentType | None:
    """Turn ``ctype`` template kwarg into a :class:`~django.contrib.contenttypes.models.ContentType`."""
    if ctype_arg is None:
        return None
    if isinstance(ctype_arg, ContentType):
        return ctype_arg
    if isinstance(ctype_arg, models.Model):
        return ContentType.objects.get_for_model(ctype_arg, for_concrete_model=False)
    if isinstance(ctype_arg, type):
        try:
            if issubclass(ctype_arg, models.Model):
                return ContentType.objects.get_for_model(ctype_arg, for_concrete_model=False)
        except TypeError:
            return None
    if isinstance(ctype_arg, str) and "." in ctype_arg:
        app_label, _, model_name = ctype_arg.partition(".")
        Model = apps.get_model(app_label, model_name)
        if Model is None:
            return None
        return ContentType.objects.get_for_model(Model, for_concrete_model=False)
    return None


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def _lookup_template_and_variant_args(
    named_id: str,
    ctype_filter: ContentType | None,
) -> tuple[DynamicTemplate | None, dict[str, object]]:
    qs = DynamicTemplate.objects.prefetch_related(
        "content_types",
        "relation_contexts",
        "relation_contexts__content_type",
    )
    if ctype_filter is not None:
        qs = qs.filter(content_types=ctype_filter)

    try:
        return qs.get(named_id=named_id), {}
    except DynamicTemplate.MultipleObjectsReturned:
        return None, {}
    except DynamicTemplate.DoesNotExist:
        pass

    try:
        variant = (
            DynamicTemplateVariant.objects.select_related("dynamic_template")
            .prefetch_related(
                "dynamic_template__content_types",
                "dynamic_template__relation_contexts",
                "dynamic_template__relation_contexts__content_type",
            )
            .get(named_id=named_id)
        )
    except (DynamicTemplateVariant.DoesNotExist, DynamicTemplateVariant.MultipleObjectsReturned):
        return None, {}

    dt = variant.dynamic_template
    if ctype_filter is not None and not dt.content_types.filter(pk=ctype_filter.pk).exists():
        return None, {}

    try:
        variant_args = parse_variant_arguments(variant.arguments)
    except (ValueError, json.JSONDecodeError):
        return None, {}

    return dt, variant_args


class DynTplNode(template.Node):
    """Render a :class:`~dynamic_template.models.DynamicTemplate` by ``named_id``.

    Usage::

        {% load dyntpl %}
        {% dyntpl my-template-named-id %}
        {% dyntpl "my-template-named-id" %}
        {% dyntpl slug_variable obj=article title=article.title %}
        {% dyntpl slug ctype=Product %}
        {% dyntpl slug ctype="myapp.Product" obj=instance %}
        {% dyntpl slug debug %}
        {% dyntpl slug arg1 arg2 %}

    A :class:`~dynamic_template.models.DynamicTemplateVariant` is resolved when
    ``named_id`` matches a variant slug; its ``arguments`` are merged into the
    render context before tag kwargs (e.g. ``{% dyntpl list-contact-only-woman %}``
    is like ``{% dyntpl list-contact woman %}`` when the variant label is ``only woman``).

    Positional names after ``named_id`` without ``=`` are passed as ``name=True``
    in the inner render context (e.g. ``{% dyntpl slug debug %}`` or
    ``{% dyntpl slug arg1 arg2 %}``).

    Inside a DB fragment, ``dyntpl`` / ``var`` and ``tz`` tags are available
    without ``{% load %}`` (see :func:`~dynamic_template.rendering.get_fragment_engine`).

    The first argument is the template's ``named_id`` (from NamedID on ``label``).
    Hyphens are allowed without quoting.  Quoted strings and template variables
    also work.

    Optional ``ctype`` narrows the lookup to that model's content type: pass a
    :class:`~django.contrib.contenttypes.models.ContentType`, a model class or instance,
    or ``"app_label.ModelName"``.  ``ctype`` is not merged into the inner template context.

    Other keyword arguments (except ``obj`` and ``ctype``) are merged into the render context.
    If ``obj`` is passed, it must be a model instance whose content type
    matches the template.
    """

    def __init__(
        self,
        named_id_literal: str | None,
        named_id_var: template.base.FilterExpression | None,
        kwargs: dict[str, template.base.FilterExpression],
    ):
        self.named_id_literal = named_id_literal
        self.named_id_var = named_id_var
        self.kwargs = kwargs

    @staticmethod
    def _resolve_dotted_path(context: template.Context, path: str):
        """Traverse ``path`` (e.g. ``meeting.group``) through the template context."""
        parts = path.split(".")
        obj = context.get(parts[0])
        for part in parts[1:]:
            if obj is None:
                return None
            obj = getattr(obj, part, None)
        return obj

    def render(self, context: template.Context) -> str:
        if self.named_id_literal is not None:
            named_id = self.named_id_literal
        else:
            named_id = self.named_id_var.resolve(context)

        kwargs = {k: v.resolve(context) for k, v in self.kwargs.items()}
        bound = kwargs.pop("obj", None)
        ctype_kw = kwargs.pop("ctype", None)
        ctype_filter = _resolve_ctype_kwarg(ctype_kw)
        if ctype_kw is not None and ctype_filter is None:
            return ""

        dt, variant_args = _lookup_template_and_variant_args(named_id, ctype_filter)
        if dt is None:
            return ""

        if bound is None and dt.context_object:
            bound = self._resolve_dotted_path(context, dt.context_object)

        if bound is not None:
            if not hasattr(bound, "_meta"):
                return ""
            try:
                ct = ContentType.objects.get_for_model(bound, for_concrete_model=False)
            except (AttributeError, TypeError):
                return ""
            if not dt.content_types.filter(pk=ct.pk).exists():
                return ""

        base: dict[str, object] = {}
        if hasattr(context, "flatten"):
            base.update(context.flatten())

        request = context.get("request")
        merged_extra = {**variant_args, **kwargs}
        try:
            return mark_safe(
                render_dynamic_template_fragment(
                    dt,
                    request=request,
                    bound=bound,
                    base_context=base,
                    extra=merged_extra,
                )
            )
        except ValueError:
            logger.warning("dyntpl: render failed for named_id=%r", named_id, exc_info=True)
            return ""


@register.tag("dyntpl")
def do_dyntpl(parser: template.base.Parser, token: template.base.Token) -> DynTplNode:
    bits = token.split_contents()
    tag_name = bits[0]
    if len(bits) < 2:
        raise template.TemplateSyntaxError(f"'{tag_name}' tag requires at least one argument (named_id)")

    named_id_literal: str | None = None
    named_id_var: template.base.FilterExpression | None = None

    first_arg = bits[1]
    if "=" in first_arg:
        raise template.TemplateSyntaxError(f"'{tag_name}' tag: first argument must be the named_id, not a keyword")

    slug_parts = [first_arg]
    idx = 2
    while idx < len(bits):
        bit = bits[idx]
        if "=" in bit:
            break
        if "-" in bit or "/" in bit:
            slug_parts.append(bit)
            idx += 1
            continue
        break
    kwarg_bits = bits[idx:]

    raw_slug = " ".join(slug_parts)
    if (raw_slug.startswith('"') and raw_slug.endswith('"')) or (
        raw_slug.startswith("'") and raw_slug.endswith("'")
    ):
        named_id_literal = _strip_quotes(raw_slug)
    elif "-" in raw_slug or "/" in raw_slug:
        named_id_literal = raw_slug
    else:
        named_id_var = parser.compile_filter(raw_slug)

    kwargs: dict[str, template.base.FilterExpression] = {}
    for bit in kwarg_bits:
        if "=" not in bit:
            kwargs[bit] = parser.compile_filter("True")
            continue
        key, _, val = bit.partition("=")
        kwargs[key] = parser.compile_filter(val)

    return DynTplNode(named_id_literal, named_id_var, kwargs)


register.tag("var", do_dyntpl)
