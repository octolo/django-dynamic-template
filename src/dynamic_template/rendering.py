"""Render :class:`~dynamic_template.models.DynamicTemplate` fragments (shared by tag and admin)."""

from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.template import Engine, engines
from django.template.context import make_context

from dynamic_template.models import DynamicTemplate

# Auto-loaded in DB fragments (no ``{% load %}`` required).
FRAGMENT_BUILTINS = (
    "dynamic_template.templatetags.dyntpl",
    "django.templatetags.tz",
)

_FRAGMENT_ENGINE: Engine | None = None


def get_fragment_engine() -> Engine:
    """Template engine for fragments with ``dyntpl`` / ``tz`` builtins."""
    global _FRAGMENT_ENGINE
    if _FRAGMENT_ENGINE is None:
        base = engines["django"].engine
        _FRAGMENT_ENGINE = Engine(
            autoescape=base.autoescape,
            string_if_invalid=base.string_if_invalid,
            builtins=list(FRAGMENT_BUILTINS),
        )
    return _FRAGMENT_ENGINE


def render_dynamic_template_fragment(
    dt: DynamicTemplate,
    *,
    request=None,
    bound: models.Model | None = None,
    base_context: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """
    Evaluate ``dt.template`` with optional ``object`` (*bound*), relation contexts, and context merges.

    Raises ``ValueError`` if *bound* is not compatible with any of ``dt.content_types``.
    """
    if bound is not None:
        if not hasattr(bound, "_meta"):
            raise ValueError("bound must be a model instance")
        ct = ContentType.objects.get_for_model(bound, for_concrete_model=False)
        if not dt.content_types.filter(pk=ct.pk).exists():
            raise ValueError("bound model does not match any template content type")

    engine = get_fragment_engine()
    tpl = engine.from_string(dt.template)

    render_ctx: dict[str, Any] = dict(base_context or {})
    if extra:
        render_ctx.update(extra)
    if bound is not None:
        render_ctx["object"] = bound

    for rel_ctx in dt.relation_contexts.select_related("content_type").all():
        render_ctx[rel_ctx.name] = rel_ctx.get_queryset(render_ctx, request)

    if bound is not None:
        render_ctx["object"] = bound if dt.raw_object else dt.freeze_bound_for_fragment(bound)

    context = make_context(render_ctx, request, autoescape=engine.autoescape)
    return tpl.render(context)
