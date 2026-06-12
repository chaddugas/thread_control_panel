# Auto-update your panel UI

Panel UIs are deliberately version-less. The **Update UI** button on the panel's device page installs your source's latest release — pressing it is the whole update story. If you'd rather not press it yourself, let GitHub press it: a release webhook into a Home Assistant automation.

## 1. The automation

Create an automation with a webhook trigger. The webhook ID is the secret in the URL — make it long and random, and treat it like a password.

```yaml
alias: Panel UI auto-update
triggers:
  - trigger: webhook
    webhook_id: "<long-random-secret>"
    allowed_methods:
      - POST
    local_only: false
conditions:
  - condition: template
    value_template: "{{ trigger.json.action == 'published' }}"
actions:
  - action: button.press
    target:
      entity_id: button.kitchen_panel_update_ui
```

`local_only` must be off — GitHub calls in from the outside. The condition filters GitHub's other release events (edited, deleted, …) down to actual publishes. Point the action at your own panel's **Update UI** button entity.

## 2. The webhook

In your UI repo: **Settings → Webhooks → Add webhook**. Payload URL `https://<your-ha>/api/webhook/<long-random-secret>`, content type `application/json`, and under "Which events…" select **Releases** only.

## 3. Ship

Publish a release. GitHub calls the webhook, the automation presses the button, and the panel downloads and hot-swaps the new bundle — no reboot.

## Caveats

- GitHub must be able to reach your Home Assistant over HTTPS — a Nabu Casa remote URL or your own publicly reachable endpoint.
- The **Update UI** button exists only while the panel has a UI source configured.
