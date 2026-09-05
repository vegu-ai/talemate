# Character perspective records

These APIs are the persistence contract for the character-knowledge series.
They require the [internal development gate](scene-format.md#internal-development-fixtures).
They do not generate perspectives or switch existing actor prompts to these views.

## Saved representation

Reader prose remains in `SceneMessage.message` or an archive entry's `text`.
Optional `knowledge` holds `SourcePerspectives` on messages, base summaries and
layered summaries. It is absent on legacy records. Scene-level `knowledge` holds
`SceneKnowledge`, with the acquisition counter and independent disclosures.
Runtime `Scene` remains an ordinary Python class.

Models live in `talemate.knowledge.perspective_models`. Records are immutable;
use the scene-aware operations below to publish changes.

| Model / field | Contract |
| --- | --- |
| `SourceReference` | `kind`: `message`, `summary` or `disclosure`. `id`: existing integer message ID or string summary/disclosure ID. `layer`: 0 for base summaries, 1 upwards for layered summaries, and 0 for other kinds. Positive `revision` identifies content. Optional `view_id` identifies a particular perspective as evidence; `view_revision` pins its version independently of reader content. |
| `SourcePerspectives.revision` | Monotonic counter starting at 1. Only reader-content changes advance it. Independent of message/changelog `rev` and the transient version stack. |
| `SourcePerspectives.content_digest` | SHA-256 of UTF-8 reader text. Selection checks exact content so out-of-band text mutations cannot serve an old view. |
| `SourcePerspectives.acquired` | `Acquisition(order, ts)`: scene-wide increasing acquisition order and scene time in seconds. Regeneration preserves the original acquisition point. |
| `SourcePerspectives.views` | Nonoverlapping `PerspectiveView` records with persisted `id`, explicit `audience`, `status`, optional `text`, and `sources` dependencies. |
| `PerspectiveView.audience` | One or more exact canonical scene character names, including inactive characters. Shared views name every recipient. Unknown names, wildcards, empty audiences, duplicates and overlapping assignments are rejected. |
| `PerspectiveView.revision` | Starts at 1; advances when this view changes or is invalidated. Unaffected siblings retain their revisions and prose. |
| `PerspectiveView.text` | Complete replacement prose, present only when ready. Never an annotation appended to reader prose. |
| `PerspectiveView.sources` | Computational dependencies on source revisions and optionally specific views. Every recipient must have current source references. Ready output additionally requires transitively readable (ready) evidence. Omitted, pending and failed outputs can cite current non-ready evidence. |
| `Disclosure` | Independent `id`, `revision`, `text`, `audience`, `acquired` and `provenance`. Its own text is learning evidence; no fact ID is required and no containing summary is unlocked. |
| `Disclosure.provenance` | Historical source references validated at creation and retained after an original source changes or disappears. Provenance is not a computational dependency. |
| `SceneKnowledge.last_order` | Highest allocated acquisition order, at least as large as every saved acquisition. A new source/disclosure receives the next order. |

Preserve attribution and uncertainty in prose: “Alice said the ledger burned”
does not assert that it burned or that the listener believes her. Storage performs
no belief inference or fact extraction.

## Publish and select

The reusable entry points live in `talemate.knowledge.perspectives`:

```python
from talemate.knowledge.perspectives import (
    add_disclosure, select_character_view,
    set_source_perspectives, source_reference,
)

reference = set_source_perspectives(scene, "message", message.id, [
    {"audience": ["Alice"], "status": "ready",
     "text": "Alice hides the ledger beneath the bed."},
    {"audience": ["Bob", "Cara"], "status": "ready",
     "text": "Alice kneels beside the bed."},
    {"audience": ["Dan"], "status": "omitted"},
])
selected = select_character_view(scene, reference, "Bob")
assert selected.status == "ready"
assert selected.text == "Alice kneels beside the bed."

disclosure = add_disclosure(
    scene, "The ledger is under the bed.", ["Bob"],
    provenance=[reference],
)
disclosure_reference = source_reference(scene, "disclosure", disclosure.id)
```

`set_source_perspectives(scene, kind, source_id, outputs, *, layer=0)` accepts
`PerspectiveOutput` objects or dictionaries and returns a `SourceReference`.
The source must already exist. Validation finishes before publication. Initial
output receives an acquisition point; replacement output retains that point.
The call replaces the complete view set. `PerspectiveOutput.id` can name an existing
view explicitly; unknown or removed explicit IDs are rejected. Omit the ID to
create a new view. Without an ID, the same audience set retains its existing ID.
Audience ordering is immaterial; a reordered audience retains its stored order.
Unchanged views retain their revision; changed views advance only their own revision.
Deliberately removed views cease to resolve. Summaries use `kind="summary"` and the appropriate layer.

`source_reference(scene, kind, source_id, *, layer=0)` returns the current reference
or `None` when no perspective/disclosure data exists, including when
`scene.knowledge` is `None` even if an individual source carries records. Invalid
message/summary kind/ID/layer combinations raise `ValueError` (including Pydantic
`ValidationError`); a nonzero layer on a message is invalid. Disclosure lookup
returns `None` for any unmatched ID, including malformed IDs, and rejects a nonzero
layer. Never use changelog `rev`.
Use the reference returned by selection to pin both source and view revisions;
source-only references pin reader content and resolve the current audience view.

**`select_character_view(scene, source, character)` is the shared selection
interface.** It returns `CharacterView`:

| Status | Meaning |
| --- | --- |
| `ready` | Complete usable text, with source/view identity and acquisition point. |
| `omitted` | Explicit saved decision that this entry is wholly unknown to the audience. |
| `pending` | Recorded work is pending, or revision/content/dependencies are stale. |
| `failed` | The producer recorded failure; no text is available. |
| `unavailable` | No record/view exists for this source/audience, or the development mode is disabled. |

Only `ready` contains text. Missing or failed views never fall back to reader
prose. Unknown characters raise a validation error in the enabled mode. Selection
checks transitive dependency revisions and audience membership, withholding stale
saved descendants even if a notification was missed. Later generation/context
tickets define retry and blocking UI.

## Edits and invalidation notifications

Message text assignment, `Scene.edit_message`, `Scene.append_message_version`
and `Scene.set_message_active_version` advance the content revision when canonical
text changes. Identical text and changelog `rev` changes do not.
`update_history_entry` applies this to every summary layer; its edit payload cannot
overwrite the stored knowledge envelope.

A reader-content edit invalidates all views of that source. A dependency edit
invalidates only descendant views that depend on the changed view, transitively.
Affected views become `pending` and lose their old character text. IDs, acquisition
points and dependency references remain available for rebuilding. Derived views
invalidate transitively; unrelated sources and independent disclosures survive.
Publishing changed perspectives invalidates their dependents; retrying one view
preserves unchanged siblings and references to them. Rebuilding uses the stable view
ID and fresh revision references; historical dependency revisions are not rewritten.
Message deletion and manual-summary deletion notify consumers.

**`PerspectiveInvalidation` on `perspectives_changed` is the notification
contract.** Import the model from `perspective_models` and the Blinker signal
from `perspectives`:

```python
from talemate.knowledge.perspectives import perspectives_changed

def on_perspectives_changed(sender, *, event):
    cache.invalidate(sender, event.affected)

perspectives_changed.connect(on_perspectives_changed, sender=scene)
```

The synchronous signal fires after records update; `sender` is the owning scene.
`source` is the previous reference, `replacement` is the current reference (or
`None` on deletion), and `affected` lists source/view references whose
cached results must be discarded. `reason`: `content`, `views`, `deleted` or
`rename`. A source reference without `view_id` invalidates all views of that source;
a reference with `view_id` invalidates that view only (and source-only cache entries
for that source). Initial publication uses the new reference in both source fields.
No-op publications emit no event. Newly added views appear with their new references.
Renaming preserves source/view revisions and updates audiences; its affected
references identify caches to discard. Consumers must key caches by scene, viewer
and source/view revision and disconnect scene-bound receivers on teardown.

`bind_perspective_sources(scene)` attaches weak ownership references to messages;
loading and publication call it automatically. Custom importers assigning already
populated messages directly must also call it. Standalone messages invalidate
their own views but cannot notify an unbound scene. Custom summary mutators must
call `source_content_changed` after committing text changes. Arbitrary dictionary
writes are not a notification API; the digest check only withholds stale views.

## Rename, reload and compatibility

Supported `Character.rename` operations in the active scene update message,
summary (all layers) and disclosure audiences. Collisions with another character's
name or occupied registry key, including case-only name collisions, are rejected
before mutation in every scene mode. Empty or noncanonical names are also rejected
in perception mode, even before its first records exist. Reusing the old
name cannot grant the former character's views. `Scene.remove_character` removes that name from every view and disclosure
audience, drops records with no recipients, and emits one `deleted` notification.
Re-adding the same name cannot inherit the removed character's evidence.
This extends existing names without another identity system or prose rewrite.

`validate_saved_knowledge` validates envelopes and audiences before scene
assignment and ZIP extraction. Stale dependencies/provenance are retained, never
rewritten to current revisions. Save, reload, export and ZIP import preserve the
representation when progress is retained. Legacy records gain no knowledge key or
reconstructed history. `Scene.reset()`, Reset Scene State with `wipe_history`, and
export with `reset_progress=True` remove all disclosures (including ones shipped in
a scene file) and all views on retained pre-established archive entries. They retain
static reader prose, the acquisition counter and scene eligibility. Export clears
only its serialized copy; the live scene is unchanged.

`tests/data/knowledge_perspectives/scene.json` demonstrates distinct/shared views,
explicit omission, pending/failure, a dependent summary and an independent later
disclosure. Downstream tickets must reuse these models, `select_character_view`
and `perspectives_changed`.
