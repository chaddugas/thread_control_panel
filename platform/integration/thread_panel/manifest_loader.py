"""Parse and validate a panel manifest from YAML text."""

from __future__ import annotations

from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class EntityDecl:
    entity_id: str
    # None = forward every attribute (the manifest said `attributes: all`).
    # Tuple = forward only those named keys.
    attributes: tuple[str, ...] | None


@dataclass(frozen=True)
class PanelManifest:
    panel_id: str
    entities: tuple[EntityDecl, ...]


class ManifestError(Exception):
    """Raised when the manifest cannot be parsed or fails validation."""


def parse_manifest(text: str) -> PanelManifest:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ManifestError(f"Manifest is not valid YAML: {e}") from e

    if not isinstance(data, dict):
        raise ManifestError("Manifest must be a YAML mapping at the top level")

    panel_id = data.get("panel_id")
    if not isinstance(panel_id, str) or not panel_id:
        raise ManifestError("Manifest must include a non-empty string 'panel_id'")

    raw_entities = data.get("entities", [])
    if not isinstance(raw_entities, list):
        raise ManifestError("Manifest 'entities' must be a list")

    entities: list[EntityDecl] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw_entities):
        if not isinstance(item, dict):
            raise ManifestError(f"entities[{idx}] must be a mapping")
        entity_id = item.get("entity_id")
        if not isinstance(entity_id, str) or "." not in entity_id:
            raise ManifestError(
                f"entities[{idx}] must have an 'entity_id' like 'domain.object_id'"
            )
        if entity_id in seen:
            raise ManifestError(f"entities[{idx}] duplicates entity_id {entity_id!r}")
        seen.add(entity_id)

        attrs_raw = item.get("attributes")
        attrs: tuple[str, ...] | None
        if attrs_raw is None:
            attrs = ()
        elif attrs_raw == "all":
            attrs = None
        elif isinstance(attrs_raw, list) and all(
            isinstance(a, str) for a in attrs_raw
        ):
            attrs = tuple(attrs_raw)
        else:
            raise ManifestError(
                f"entities[{idx}].attributes must be a list of strings, "
                f"the string 'all', or omitted"
            )
        entities.append(EntityDecl(entity_id=entity_id, attributes=attrs))

    return PanelManifest(panel_id=panel_id, entities=tuple(entities))
