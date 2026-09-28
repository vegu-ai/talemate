# Template Overrides

A template override is your own copy of a default prompt template. Talemate uses the copy instead of the default wherever that template is rendered, for example to change how the narrator is asked to describe a scene. Overrides live in an editable [template group](index.md#template-groups): **user**, **scene** or a custom group. The [priority order](index.md#priority-order) decides which copy wins when several groups have one.

## Override a default template

Templates in the `default` group are read-only. To change one, make a copy in an editable group:

1. Open **Prompts → Template Files → Active** and locate the template you want to customize.
2. View its content in the default group.
3. Switch to the target group tab, for example **user**.
4. Create a new template with the same agent directory and filename.
5. Paste and change the content.

To edit an existing override, open its group tab and select the file. The built-in editor opens with the full Jinja2 source. To go back to the default, delete the override.

Templates are standard Jinja2 files with access to Talemate's template context variables and functions. The [template function reference](/talemate/user-guide/node-editor/reference/template_functions/) lists the functions.

## Keep overrides current

A new Talemate version can change a default template that you have overridden. Your copy then keeps the old wording and misses the change. The **Prompts** tab shows a warning icon when an active override is older than its default, and the **Active** tab marks the templates in question with the [outdated indicator](index.md#override-indicators). Compare each one with the current default and update it, or delete it.

## World snapshot overrides

World snapshot overrides must use `snapshot_request.context_history(...)` to supply their broad story history after memory retrieval. Older copies of `world_state/request-world-state-v2.jinja2` that call only `scene.context_history(...)` cannot establish the inputs needed for safe snapshot regeneration. This also applies to `world_state/add-snapshot-entity.jinja2` overrides.

Put the call after the memory retrieval and any other context that can run agent actions, and render the history it returns:

```jinja2
{% set background_history = snapshot_request.context_history(budget=background_budget) %}
{% for line in background_history %}
{{ line }}
{% endfor %}
```

The call records where the story history ended when it was read. If a message arrives during memory retrieval, it becomes part of the snapshot's source; if an earlier message is edited or deleted, the result is discarded. Do not replace the call with `scene.context_history`, and do not read the history before the memory retrieval.

If Talemate reports an incompatible snapshot prompt, open **Template Files → Active** in the Prompt Manager and locate the template named in the notice. Compare it with the current default and update your override, or delete the override to restore the default. An incompatible result is not applied; Talemate makes no automatic retry.
