import json

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel, admin_boost_view
from django_boosted.decorators import AdminBoostViewConfig

from .relation_context import DynamicRelationContextInline
from .variant import DynamicTemplateVariantInline
from dynamic_template.fixtures import discover_dyntpl_fixture_files, load_dyntpl_fixtures
from dynamic_template.io import (
    archive_attachment_response,
    build_export_archive,
    import_payload,
    json_attachment_response,
    safe_export_stem,
    serialize_export,
)
from dynamic_template.models import DynamicTemplate
from dynamic_template.rendering import render_dynamic_template_fragment
from dynamic_template.variant_args import parse_variant_arguments


class PreviewByContentTypeArgumentsForm(forms.Form):
    arguments = forms.CharField(
        label=_("Arguments"),
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 4, "cols": 80, "class": "vLargeTextField"},
        ),
        help_text=_(
            'JSON object merged into the fragment context. Example: {"debug": true, "title": "Hello"}.'
        ),
        initial="{}",
    )

    def clean_arguments(self):
        text = (self.cleaned_data.get("arguments") or "").strip() or "{}"
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(str(exc)) from exc
        if not isinstance(parsed, dict):
            raise forms.ValidationError(_("Arguments must be a JSON object."))
        return parsed


def _render_content_type_previews(
    obj: DynamicTemplate,
    *,
    request,
    extra: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    previews: list[dict[str, object]] = []
    context_extra = extra or {}
    variants = list(obj.variants.all())

    for ct in obj.content_types.all():
        Model = ct.model_class()
        model_label = Model._meta.label if Model else str(ct)

        preview: dict[str, object] = {
            "content_type": ct,
            "model_label": model_label,
            "object_id": None,
            "html": None,
            "error": None,
            "bound_label": None,
            "variants": [],
        }

        if Model is None:
            preview["error"] = _("Unknown content type.")
            previews.append(preview)
            continue

        bound = Model.objects.first()
        if bound is None:
            preview["error"] = _(
                "No %(model)s instance available for an example."
            ) % {"model": Model._meta.verbose_name}
            previews.append(preview)
            continue

        preview["object_id"] = str(bound.pk)
        preview["bound_label"] = str(bound)
        try:
            preview["html"] = render_dynamic_template_fragment(
                obj,
                request=request,
                bound=bound,
                base_context={},
                extra=context_extra,
            )
        except ValueError as exc:
            preview["error"] = str(exc)
            previews.append(preview)
            continue

        for variant in variants:
            variant_preview: dict[str, object] = {
                "label": variant.label,
                "named_id": variant.named_id,
                "arguments": variant.arguments,
                "html": None,
                "error": None,
            }
            try:
                merged_extra = {**parse_variant_arguments(variant.arguments), **context_extra}
                variant_preview["html"] = render_dynamic_template_fragment(
                    obj,
                    request=request,
                    bound=bound,
                    base_context={},
                    extra=merged_extra,
                )
            except (ValueError, json.JSONDecodeError) as exc:
                variant_preview["error"] = str(exc)
            preview["variants"].append(variant_preview)

        previews.append(preview)

    return previews


class DynamicTemplateImportForm(forms.Form):
    file = forms.FileField(label=_("JSON file"), required=False)
    payload = forms.CharField(
        label=_("Or paste JSON"),
        widget=forms.Textarea(attrs={"rows": 24, "cols": 100, "class": "vLargeTextField"}),
        required=False,
    )
    replace = forms.BooleanField(
        label=_("Replace existing templates (same content type + label)"),
        required=False,
        initial=True,
    )

    def clean(self):
        cleaned = super().clean()
        file = cleaned.get("file")
        text = (cleaned.get("payload") or "").strip()
        raw: str | None = None
        if file:
            data = file.read()
            raw = data.decode("utf-8") if isinstance(data, bytes) else str(data)
        elif text:
            raw = text
        if not raw:
            raise forms.ValidationError(_("Provide a JSON file or paste JSON."))
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(str(exc)) from exc
        if not isinstance(parsed, dict):
            raise forms.ValidationError(_("Root JSON value must be an object."))
        cleaned["parsed"] = parsed
        return cleaned


@admin.register(DynamicTemplate)
class DynamicTemplateAdmin(AdminBoostModel):
    list_display = ("label", "named_id", "content_types_display", "relation_context_count_display")
    list_filter = ("content_types",)
    search_fields = ("label", "named_id", "template")
    readonly_fields = ("named_id",)
    filter_horizontal = ("content_types",)

    def change_fieldsets(self):
        self.add_to_fieldset(None, ("label", "named_id", "content_types",))
        self.add_to_fieldset(_("Template"), ("template",))
        self.add_to_fieldset(_("Context"), ("raw_object", "context_object",))
        self.add_to_fieldset(_("Fields"), ("model_fields", "annotate_fields", "fields",))


    @admin.display(description=_("Content types"))
    def content_types_display(self, obj):
        return ", ".join(str(ct) for ct in obj.content_types.all()) or "—"
    inlines = (DynamicRelationContextInline, DynamicTemplateVariantInline)

    def get_queryset(self, request):
        return super().get_queryset(request).with_relation_context_count()

    @admin.display(
        ordering="relation_context_count",
        description=_("Relation contexts"),
    )
    def relation_context_count_display(self, obj):
        return getattr(obj, "relation_context_count", 0)

    @admin_boost_view(
        "adminform",
        _("Import JSON"),
        config=AdminBoostViewConfig(
            path_fragment="import-json",
            requires_object=False,
            permission="change",
        ),
    )
    def admin_import_json(self, request, form=None):
        if not self.has_change_permission(request):
            raise PermissionDenied
        if form is None:
            return {"form": DynamicTemplateImportForm()}
        result = import_payload(
            form.cleaned_data["parsed"],
            replace=form.cleaned_data.get("replace", True),
        )
        messages.success(
            request,
            _("Import finished: %(c)d created, %(u)d updated.")
            % {"c": result["created"], "u": result["updated"]},
        )
        for err in result["errors"][:25]:
            messages.warning(request, err)
        url = reverse(
            f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist",
            current_app=self.admin_site.name,
        )
        return {"redirect_url": url}

    @admin_boost_view(
        "confirm",
        _("Load app fixtures"),
        config=AdminBoostViewConfig(
            path_fragment="load-fixtures",
            requires_object=False,
            permission="change",
        ),
    )
    def admin_load_fixtures(self, request, confirmed=False):
        if not self.has_change_permission(request):
            raise PermissionDenied

        fixtures = discover_dyntpl_fixture_files()
        if confirmed:
            result = load_dyntpl_fixtures(replace=True)
            if result.files_loaded:
                messages.success(
                    request,
                    _("Fixtures loaded: %(files)d file(s), %(c)d created, %(u)d updated.")
                    % {
                        "files": result.files_loaded,
                        "c": result.created,
                        "u": result.updated,
                    },
                )
            else:
                messages.warning(request, _("No dyntpl fixture files found."))
            for err in result.errors[:25]:
                messages.warning(request, err)
            return {}

        if not fixtures:
            return {
                "confirm": _("No dyntpl/*.json or fixtures/dyntpl/*.json files found in installed apps."),
            }

        listing = ", ".join(f"{f.app_label}/{f.relative_path}" for f in fixtures)
        return {
            "confirm": _(
                "Replace existing templates with fixtures from installed apps? Files: %(files)s"
            )
            % {"files": listing},
        }

    @admin_boost_view(
        "json",
        _("Export JSON (all)"),
        config=AdminBoostViewConfig(
            path_fragment="export-json-bulk",
            requires_object=False,
            permission="view",
        ),
    )
    def admin_export_json_bulk(self, request):
        qs = self.get_queryset(request).prefetch_related("relation_contexts")
        return json_attachment_response("dynamic-templates.json", serialize_export(qs))

    @admin_boost_view(
        "json",
        _("Export JSON"),
        config=AdminBoostViewConfig(
            path_fragment="export-json",
            requires_object=True,
            permission="view",
        ),
    )
    def admin_export_json_single(self, request, obj):
        payload = serialize_export(
            DynamicTemplate.objects.filter(pk=obj.pk).prefetch_related("relation_contexts"),
        )
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in obj.named_id)[:80]
        return json_attachment_response(
            f"dynamic-template-{obj.pk}-{safe}.json",
            payload,
        )

    @admin_boost_view(
        "json",
        _("Export archive (all)"),
        config=AdminBoostViewConfig(
            path_fragment="export-archive-bulk",
            requires_object=False,
            permission="view",
        ),
    )
    def admin_export_archive_bulk(self, request):
        qs = self.get_queryset(request)
        return archive_attachment_response(
            "dynamic-templates.zip",
            build_export_archive(qs),
        )

    @admin_boost_view(
        "json",
        _("Export archive"),
        config=AdminBoostViewConfig(
            path_fragment="export-archive",
            requires_object=True,
            permission="view",
        ),
    )
    def admin_export_archive_single(self, request, obj):
        qs = DynamicTemplate.objects.filter(pk=obj.pk)
        safe = safe_export_stem(obj.named_id, obj.pk)
        return archive_attachment_response(
            f"dynamic-template-{safe}.zip",
            build_export_archive(qs),
        )

    @admin_boost_view(
        "adminform",
        _("Preview by content type"),
        config=AdminBoostViewConfig(
            template_name="dynamic_template/admin/preview_by_content_type.html",
            path_fragment="preview-by-content-type",
            permission="change",
        ),
    )
    def admin_preview_by_content_type(self, request, obj, form=None):
        obj = DynamicTemplate.objects.prefetch_related("content_types", "variants").get(pk=obj.pk)
        if form is None:
            extra: dict[str, object] = {}
        else:
            extra = form.cleaned_data.get("arguments") or {}

        return {
            "form": form or PreviewByContentTypeArgumentsForm(),
            "content_type_previews": _render_content_type_previews(
                obj,
                request=request,
                extra=extra if form is None or form.is_valid() else {},
            ),
            "no_content_types": not obj.content_types.exists(),
        }
