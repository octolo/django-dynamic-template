"""Discover and load ``dyntpl/*.json`` fixtures from installed Django apps."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from django.apps import apps

from dynamic_template.io import EXPORT_FORMAT_VERSION, import_payload

DYNTPL_FIXTURE_DIRS = ("dyntpl", "fixtures/dyntpl")


@dataclass(frozen=True)
class DyntplFixtureFile:
    app_label: str
    path: Path
    relative_path: str


@dataclass
class DyntplFixtureLoadResult:
    created: int = 0
    updated: int = 0
    files_loaded: int = 0
    errors: list[str] = field(default_factory=list)


def discover_dyntpl_fixture_files(
    app_labels: Iterable[str] | None = None,
) -> list[DyntplFixtureFile]:
    """Return JSON fixtures from ``dyntpl/`` and ``fixtures/dyntpl/`` in each installed app."""
    labels = set(app_labels) if app_labels else None
    found: list[DyntplFixtureFile] = []

    for app_config in apps.get_app_configs():
        if labels is not None and app_config.label not in labels:
            continue
        app_path = getattr(app_config, "path", None)
        if not app_path:
            continue
        base = Path(app_path)
        for subdir in DYNTPL_FIXTURE_DIRS:
            directory = base / subdir
            if not directory.is_dir():
                continue
            for json_path in sorted(directory.glob("*.json")):
                found.append(
                    DyntplFixtureFile(
                        app_label=app_config.label,
                        path=json_path,
                        relative_path=f"{subdir}/{json_path.name}",
                    )
                )
    return found


def normalize_fixture_payload(data: object) -> dict:
    """Accept export payloads or a single template object."""
    if not isinstance(data, dict):
        raise ValueError("Fixture root must be a JSON object.")
    if data.get("dynamic_templates") is not None or data.get("templates") is not None:
        return data
    if "label" in data:
        return {
            "format_version": EXPORT_FORMAT_VERSION,
            "dynamic_templates": [data],
        }
    raise ValueError(
        "Fixture must be an export payload with 'dynamic_templates' or a single template object."
    )


def load_dyntpl_fixtures(
    *,
    replace: bool = True,
    app_labels: Iterable[str] | None = None,
) -> DyntplFixtureLoadResult:
    """Load or replace templates from discovered fixture files."""
    result = DyntplFixtureLoadResult()
    for fixture in discover_dyntpl_fixture_files(app_labels):
        prefix = f"{fixture.app_label}/{fixture.relative_path}"
        try:
            raw = fixture.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            payload = normalize_fixture_payload(data)
            imported = import_payload(payload, replace=replace)
            result.created += imported["created"]
            result.updated += imported["updated"]
            result.files_loaded += 1
            for err in imported["errors"]:
                result.errors.append(f"{prefix}: {err}")
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            result.errors.append(f"{prefix}: {exc}")
    return result
