# feeding_control/ha/

Reference templates for the HA-side configuration of the `feeding_control` panel.

- `manifest.yaml` — starting point for the integration config flow. Copy its contents, replace placeholder entity_ids with your actual PetLibro entities, paste into the `thread_panel` integration's "Add Thread Panel" form.

Nothing in this directory is deployed to Home Assistant. The integration itself lives at the repo root under `custom_components/thread_panel/` (HACS requirement); this directory just hosts product-specific reference material.

If this product ever needs non-entity-shaped HA-side logic (e.g. a REST fetch that doesn't fit the "mirror an HA entity" model), a Python module can live here and be registered with the integration's extension hook. Not needed for V1 — feeding_control's product surface is fully expressible as forwarded HA entities + service calls.
