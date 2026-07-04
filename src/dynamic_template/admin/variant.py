from django.contrib import admin

from dynamic_template.models import DynamicTemplateVariant


class DynamicTemplateVariantInline(admin.TabularInline):
    model = DynamicTemplateVariant
    extra = 0
    readonly_fields = ("named_id",)
    fields = ("label", "named_id", "arguments")
