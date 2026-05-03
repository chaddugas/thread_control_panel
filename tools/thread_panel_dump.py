"""
thread_panel_dump — pyscript service that enumerates every entity attached to a
HA device, with each entity's current state and full attribute dict. Used when
authoring a thread_panel manifest, to see what an integration actually exposes.

Install:
  Copy this file to /config/pyscript/thread_panel_dump.py on your HA box
  (create the directory if it doesn't exist), then reload pyscript via the
  Pyscript integration page (Settings -> Devices & Services -> Pyscript ->
  Reload) or restart HA.

  If pyscript errors on the homeassistant.helpers imports, set
  `allow_all_imports: true` in the pyscript config (configuration.yaml) and
  reload.

Call (Developer Tools -> Actions):
  action: pyscript.thread_panel_dump
  data:
    device_id: <id from device page URL: /config/devices/device/<id>>

  ...or fuzzy-match by name (substring, case-insensitive):
  action: pyscript.thread_panel_dump
  data:
    device_name: "Pet Feeder"

  Tick "Return response data" — the dump comes back inline.
"""


def _coerce(value):
    """Coerce HA state values to JSON-serializable shapes."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_coerce(v) for v in value]
    return str(value)


@service(supports_response="only")
def thread_panel_dump(device_id=None, device_name=None):
    """Return a HA device's entities + state + attributes as service response."""
    from homeassistant.helpers import device_registry as dr_mod
    from homeassistant.helpers import entity_registry as er_mod

    dr = dr_mod.async_get(hass)
    er = er_mod.async_get(hass)

    device = None
    matches = []
    if device_id:
        device = dr.async_get(device_id)
    elif device_name:
        needle = device_name.lower()
        for d in dr.devices.values():
            for cand in (d.name_by_user, d.name):
                if cand and needle in cand.lower():
                    matches.append(d)
                    break
        if len(matches) == 1:
            device = matches[0]
        elif len(matches) > 1:
            names = [f"{m.name_by_user or m.name} ({m.id})" for m in matches]
            return {
                "error": f"{len(matches)} devices match {device_name!r} — pass device_id instead",
                "candidates": names,
            }

    if not device:
        return {
            "error": "no device found",
            "device_id": device_id,
            "device_name": device_name,
        }

    entries = er_mod.async_entries_for_device(
        er, device.id, include_disabled_entities=True
    )

    out = {
        "device": {
            "id": device.id,
            "name": device.name_by_user or device.name,
            "manufacturer": device.manufacturer,
            "model": device.model,
        },
        "entities": [],
    }

    for entry in entries:
        state = hass.states.get(entry.entity_id)
        out["entities"].append({
            "entity_id": entry.entity_id,
            "friendly_name": entry.name or entry.original_name,
            "domain": entry.domain,
            "platform": entry.platform,
            "disabled": bool(entry.disabled),
            "state": state.state if state else None,
            "attributes": _coerce(dict(state.attributes)) if state else {},
        })

    log.info(
        f"thread_panel_dump: returning {len(out['entities'])} entities "
        f"for '{out['device']['name']}'"
    )
    return out
