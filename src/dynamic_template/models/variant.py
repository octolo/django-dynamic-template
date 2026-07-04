from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _
from namedid import NamedIDField

from .template import DynamicTemplate


class DynamicTemplateVariant(models.Model):
    """
    Named shortcut for a :class:`DynamicTemplate` with preset render arguments.

    ``{% dyntpl my-variant %}`` renders ``dynamic_template`` with ``arguments``
    merged into the fragment context (same keys as ``{% dyntpl slug woman %}``).
    """

    dynamic_template = models.ForeignKey(
        DynamicTemplate,
        on_delete=models.CASCADE,
        related_name="variants",
        verbose_name=_("dynamic template"),
    )
    label = models.CharField(
        _("label"),
        max_length=255,
        help_text=_(
            "Variant suffix (e.g. « only woman »). "
            "`named_id` is built as `<template.named_id>-<label>`."
        ),
    )
    named_id = NamedIDField(
        source_fields=["parent_named_id", "label"],
        unique=True,
        max_length=255,
    )
    arguments = models.TextField(
        _("arguments"),
        blank=True,
        default="",
        help_text=_(
            "Shortcut arguments merged into the fragment context. "
            "Space-separated flags (``woman`` → ``woman=True``), "
            "``key=value`` pairs (``woman=true``), or a JSON object."
        ),
    )

    class Meta:
        verbose_name = _("dynamic template variant")
        verbose_name_plural = _("dynamic template variants")

    @property
    def parent_named_id(self) -> str | None:
        """Fresh parent slug from DB (used by :class:`~namedid.NamedIDField`)."""
        if not self.dynamic_template_id:
            return None
        return (
            DynamicTemplate.objects.filter(pk=self.dynamic_template_id)
            .values_list("named_id", flat=True)
            .first()
        )

    def expected_named_id(self) -> str:
        field = self._meta.get_field("named_id")
        return field._generate_base_value(self)

    def named_id_needs_resync(self) -> bool:
        parent = self.parent_named_id
        if not parent or not (self.label or "").strip():
            return False
        expected = self.expected_named_id()
        return bool(expected) and self.named_id != expected

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.pk:
            self.refresh_from_db(fields=["named_id"])

    def __str__(self) -> str:
        return f"{self.label} ({self.named_id}) → {self.dynamic_template_id}"
