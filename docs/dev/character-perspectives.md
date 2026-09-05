# Character perspective records

These APIs are the persistence contract for the character-knowledge series.
They require the [internal development gate](scene-format.md#internal-development-fixtures).
The summarizer generates message perspectives through the lifecycle below.
Switching existing actor context and summary pipelines to these views remains
separate work in the series.

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
| `PerspectiveView.passage_provenance` | Direct analytical inputs, each a `PassageProvenance(message_id, content_digest, revision)`; revision is optional for untracked historical prose. These reference reader passages without granting audience access or following their views' dependencies. Generated ready and omitted views always record their own passage, plus specifically cited prior physical context. |
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
saved descendants even if a notification was missed. The message lifecycle below
defines retry and blocking; summary producers remain separate.

## Finalized-passage analysis

`SummarizeAgent.finalize_perceptions(scene, messages)` registers newly finalized
character, player and narrator passages and awaits their audience views.
`Scene.push_history` calls it after the editor's revision hook and before
new-message and archive hooks. It runs even when automatic archiving is disabled
or its threshold has not been reached. In-place regeneration invokes the same
entry point after the final canonical version is installed.

`SummarizeAgent.ensure_perceptions(scene)` finishes existing pending or failed
message records before dependent conversation or narrator generation. Explicit
message edits/version changes schedule `rebuild_perceptions` using the existing
background-task mechanism. The edit and save return to the websocket receive loop
while re-analysis runs, so Retry/Cancel/Ignore frames remain dispatchable. Dependent
generation still awaits required views. Untouched historical messages
without records are not backfilled. An ordinary save/load retains incomplete
records so the next dependent generation can retry them. A finalized passage with
no relevant cast receives no empty record; the live lifecycle defers it until a cast
is available. This runtime deferral does not backfill untracked history after reload.

The internal development predicate from `talemate.knowledge.mode` governs all
new requests. The legacy learned-this-turn ledger is disabled only in this mode.
No public setting or character activation behavior is added.

The shared `summarizer.perceptions` prompt makes one analytical request per
finalized source attempt for the relevant cast: the union of the passage's persisted
presence list and currently active characters, resolved to canonical scene names.
Other inactive character records are excluded. The answer budget is at least 2048
tokens and scales as audience count times (source token count plus 256), using the
client's dynamic analysis kind. The request uses
up to 12 preceding character/narrator passages as physical author context,
the audience's ready views from that window and earlier disclosures, and authored
character descriptions/details plus the shared scene description/story intention.
Author context does not imply that a character observed it. Responses contain one
complete replacement view per character, or an explicit omission. Validation
rejects missing/duplicate/unknown audiences, unfinished statuses, empty ready
text and model-supplied identities, dependency references or activation fields.
The response includes explicit `knowledge_ids` and `passage_ids` arrays per audience,
naming only the supplied inputs actually used; empty arrays mean none. The host
rejects unknown or cross-audience knowledge IDs and resolves the IDs to its own
references. Merely appearing in the 12-passage context window does not establish a
dependency. The shared code-block extractor accepts bare structured JSON, fenced
JSON with surrounding prose, uppercase language tags and open fences before strict
schema validation. Complete JSON and JSON inside a fence are decoded before fence
matching, so literal triple backticks inside replacement prose are preserved.

Used ready knowledge goes in `sources` and retains transitive invalidation.
Used physical context goes in `passage_provenance`, independent of whether that
audience had a ready, omitted or unavailable view of it. A prior unconsciousness
passage can therefore justify an omission and invalidate it when edited. Provenance
follows the referenced reader revision/digest, not that passage's analytical views;
editing an unrelated early passage does not create a rolling dependency through the
whole tail. `MAX_DEPENDENCY_DEPTH` bounds a path to 32 dependency edges. A view at
that limit remains readable but `can_cite_view` excludes it from a new request's
established-knowledge inputs; publication rejects a dependency that would exceed
the limit. No dependency is silently truncated. Existing over-limit records select
as pending and the lifecycle rebuilds them with bounded inputs. This bounds path
depth, not the number of unrelated views that can directly cite a shared source.

`PerspectiveReadContext(scene)` builds a source index once and memoizes successful
freshness depths per audience, reference and readability requirement, separately
from cycle detection. Cached depths are checked against the remaining path budget.
Pass it as `read=` to `source_reference`, `select_character_view` and `can_cite_view`
when reading a batch. The summarizer shares one context across each pending scan
and each prompt-context build. Indexed lookup is constant-time; building the index
and scanning the scene still take linear work. A read context belongs to one scene
and one synchronous, mutation-free read: discard it before any mutation or await.

Pending/failed states use the existing perspective records and notifications.
The summarizer serializes work within a scene, so concurrent callers do not
duplicate analysis. A retry retains the passage ID, acquisition point and existing
audience view identities. Current unaffected views remain unchanged when a sibling
requires rebuilding. Source revisions and the analytical input snapshot are checked
after each request; stale output after editing, deletion, reset or character
changes is discarded. A changed source is analyzed again before dependents proceed.

Request failures use the existing generation-error dialog. Malformed analysis
also opens that dialog and records failed views. **Retry** analyzes the current
passage again. **Cancel** or **Ignore** stops dependent generation; neither grants
access to reader prose. The already-finalized reader passage remains in history
and is emitted even when its analysis is cancelled. Retrying never pushes a second
copy of that passage. Transport retries handled inside the client remain pending
until the client returns or cancels.

Schema validation proves the response structure, not whether the model interpreted
a whisper or private thought faithfully. The prompt forbids invented events,
observations, arrivals, awakenings and beliefs, and preserves claims as attributed
claims. `tests/data/perceptions/passages.json` supplies public/private, whisper and
unconscious-bystander examples for deterministic orchestration and real-model smoke
evaluation. The bounded physical-context window can miss older situational details;
this step adds no historical reconstruction or long-term perception retrieval.

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
`None` on deletion or an edit to untracked physical provenance), and `affected` lists source/view references whose
cached results must be discarded. `reason`: `content`, `views`, `deleted` or
`rename`. A source reference without `view_id` invalidates all views of that source;
a reference with `view_id` invalidates that view only (and source-only cache entries
for that source). Initial publication uses the new reference in both source fields.
No-op publications emit no event. Newly added views appear with their new references.
Renaming preserves source/view revisions and updates audiences; its affected
references identify caches to discard. Consumers must key caches by scene, viewer
and source/view revision and disconnect scene-bound receivers on teardown.

`bind_perspective_sources(scene)` attaches weak ownership references to messages;
loading and publication call it automatically for all messages, including reader
passages used as physical provenance without their own views. Custom importers
assigning already populated messages directly must also call it. Standalone messages invalidate
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
