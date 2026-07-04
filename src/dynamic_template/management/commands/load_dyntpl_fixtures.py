from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _

from dynamic_template.fixtures import discover_dyntpl_fixture_files, load_dyntpl_fixtures


class Command(BaseCommand):
    help = _(
        "Load DynamicTemplate JSON fixtures from dyntpl/*.json or fixtures/dyntpl/*.json "
        "in installed apps."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-replace",
            action="store_true",
            help=_("Skip templates that already exist (by label) instead of replacing them."),
        )
        parser.add_argument(
            "--app",
            action="append",
            dest="apps",
            metavar="APP_LABEL",
            help=_("Only scan the given app label (repeatable)."),
        )

    def handle(self, *args, **options):
        replace = not options["no_replace"]
        app_labels = options["apps"]
        fixtures = discover_dyntpl_fixture_files(app_labels)

        if not fixtures:
            self.stdout.write(_("No dyntpl fixture files found."))
            return

        for fixture in fixtures:
            self.stdout.write(f"  {fixture.app_label}/{fixture.relative_path}")

        result = load_dyntpl_fixtures(replace=replace, app_labels=app_labels)
        self.stdout.write(
            self.style.SUCCESS(
                _("Loaded %(files)d file(s): %(c)d created, %(u)d updated.")
                % {
                    "files": result.files_loaded,
                    "c": result.created,
                    "u": result.updated,
                }
            )
        )
        for err in result.errors:
            self.stderr.write(self.style.WARNING(err))
