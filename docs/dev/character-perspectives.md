# Character perspective records

These APIs are the persistence contract for the character-knowledge series.
They use the [public scene opt-in](scene-format.md#public-opt-in).
The summarizer generates message perspectives through the lifecycle below.
Perception-mode actor recent history and character-facing editor context use
stored views and audience summaries. Source-supported fact extraction and graph
queries extend those same records. Offscreen-life narration, RAG input and the
optional memory pass also use viewer-specific evidence.

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

### Introduction source

Scenes persist `intro_present` separately from the existing `intro` text. In perception mode, `intro_knowledge` holds a deterministic ready view of that text for the recorded audience, addressed by `SourceReference(kind="intro", id="intro", ...)`. It uses the existing revision, citation, memory-index and snapshot-evidence checks. Intro replacement invalidates dependent evidence; it does not request a perception rewrite.

Character history projection includes the eligible introduction within its token budget. It remains a separate opening source rather than creating another audience-summary or fact-extraction request. Standard collectors first select history with the full budget, then allocate a separate eligible intro only if the selected summaries do not carry it for that viewer. A summary that already carries the opening costs no separate intro reservation. If the reduced allocation selects an opening summary instead of dialogue, collection keeps that summary so the character retains the opening, accepting the unused intro reservation. Opening coverage skips static history notes and follows the original archive indices through layered and best-fit selection. Unscoped callers (`perspective=None`, including director, creator and author-facing templates) keep the separate intro only when no summaries or dialogue expanded from them are selected. The shared first archive only includes the intro when its entire known dialogue audience witnessed it; `intro_included: false` keeps the opening available separately to its own audience.

Missing audiences on load use the first narrative message's explicit presence, otherwise the restored active roster. Explicit empty lists survive. This is a one-time load convention for saves predating the field, not historical reconstruction.

### Character context review

The Summarizer `context_review` WebSocket action accepts an optional active `character` and echoes `request_id`. The Conversation template and preview use `history_context` to resolve the same history audience and director-message settings. Standard previews reuse the history collectors; Perspectives previews obtain entry metadata from `project_character_history(entries=...)`, so labels do not introduce another selector.

`knowledge.review` adds the existing fact, absence and analysis renderers plus author-facing exclusion diagnostics. The selectors report exclusions through `ContextDiagnostics`, including base archive and layer identities; counts cover all decisions while samples are capped at 20 per reason and 500 characters. Known facts use the shared bounded renderer, preserve false markers, and report budget cuts. Character previews derive their default budget from the Conversation client’s context window. Exclusions are separate from rendered character sections. Previewing never generates missing analysis or runs dynamic RAG retrieval, and history-budget overrides do not mutate agent settings. The existing Apply action remains scene-wide.

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
| `unavailable` | No record/view exists for this source/audience, or the scene uses legacy mode. |

Only `ready` contains text. Missing or failed views never fall back to reader
prose. Unknown characters raise a validation error in the enabled mode. Selection
checks transitive dependency revisions and audience membership, withholding stale
saved descendants even if a notification was missed. The message lifecycle below
defines retry and blocking; summary producers remain separate.

## Finalized-passage analysis

`SummarizeAgent.finalize_perceptions(scene, messages)` registers newly finalized
character, player, narrator, reinforcement and investigation passages and awaits their audience views. Non-sequential reinforcement passages share this lifecycle through their persisted source records; see [reinforcement and investigation perspectives](reinforcement-investigation-perspectives.md).
`Scene.push_history` calls it after the editor's revision hook and before
new-message and archive hooks. It runs even when automatic archiving is disabled
or its threshold has not been reached. In-place regeneration invokes the same
entry point after the final canonical version is installed.

`SummarizeAgent.ensure_perceptions(scene, *, before_message_id=None)` finishes existing pending or failed
message records before dependent conversation or narrator generation. Character
revisions pass their target ID: only passages strictly before that target are
registered or analyzed, and the boundary is rechecked after awaits. A later failed
passage cannot block an earlier revision. Per-message cancellation counters retain
every failure since a waiter's snapshot, so a later failure cannot mask an earlier
cancellation inside its prefix, including repeated failures of the same message.
A removed boundary cancels the operation. Explicit
message edits/version changes schedule `rebuild_perceptions` using the existing
background-task mechanism. The edit and save return to the websocket receive loop
while re-analysis runs, so Retry/Cancel/Ignore frames remain dispatchable. Dependent
generation still awaits required views. Untouched historical messages
without records are not backfilled. An ordinary save/load retains incomplete
records so the next dependent generation can retry them. A finalized passage with
no relevant cast receives no empty record; the live lifecycle defers it until a cast
is available. This runtime deferral does not backfill untracked history after reload.

The shared scene-mode predicate from `talemate.knowledge.mode` governs all
new requests. The legacy learned-this-turn ledger is disabled only in this mode.
Activation uses the public new-story opt-in; perception does not manage character activation.

The shared `summarizer.perceptions` prompt makes one analytical request per
finalized source attempt for the relevant cast: the union of the passage's persisted
presence list and currently active characters, resolved to canonical scene names.
Other inactive character records are excluded. The answer budget is at least 2048
tokens and scales as audience count times (source token count plus 256), using the
client's dynamic analysis kind. The request uses
up to 12 preceding eligible passages as physical author context,
the audience's ready views from that window and earlier disclosures, and authored
character descriptions/details plus the shared scene description/story intention.
Author context does not imply that a character observed it. Responses contain one
complete replacement view per character, or an explicit omission. Validation
keeps the first valid view for each requested canonical audience. Unrequested
audiences, extra fields and model-supplied identities/references are ignored.
Invalid views leave their audience missing; they do not discard valid siblings.
The response includes explicit `knowledge_ids` and `passage_ids` arrays per audience,
naming only the supplied inputs actually used; empty arrays mean none. The host
drops unknown or cross-audience knowledge IDs with audience/ID warnings and
resolves offered IDs to its own references. Unknown physical citations are also
dropped with warnings. Current-passage citations are silently ignored because
the host records that passage exactly once. Missing or malformed citation arrays and
wrongly typed IDs invalidate that view and require repair, with audience/field
warnings. Only explicit empty arrays mean no dependencies. Merely appearing in
the 12-passage context window does not establish a dependency. The shared code-block extractor accepts bare structured JSON, fenced
JSON with surrounding prose, uppercase language tags and open fences before
validating each requested view independently. Persistence models remain strict. Complete JSON and JSON inside a fence are decoded before fence
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

The Summarizer `perceptions.automatic_repair` setting defaults to true. Missing
valid views trigger at most one automatic repair request per attempt, with the
validation reason and only the missing cast. Already valid views are kept.
Turning the setting off goes directly to the generation-error dialog. Invalid
JSON or a missing views array counts as no valid views. Transport errors do not
trigger this validation repair. Request failures and unsuccessful repairs use
the existing generation-error dialog, including the underlying reason. Valid
siblings remain saved; only unresolved views are marked failed. **Retry** analyzes the current
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

## Character history projection

`talemate.knowledge.context.project_character_history(scene, character, *,
budget=None, max_messages=None, before_message_id=None, keep_director=False,
show_hidden=False, direction_mode="direction")` is the shared projection point
for actor history and character-facing editor context, including stored base and
layered audience summaries. Later supplemental-context steps should extend this
function rather than introduce a second audience selector. It requires perception mode and a canonical character
name, and reads through `select_character_view` with one `PerspectiveReadContext`.

The result is chronological replacement prose from summaries and eligible
messages. Character and narrator messages use the source type's `as_format` on a temporary
copy; reinforcement and investigation views use plain replacement formatting so reader headings cannot reappear. Character names come from the source message, not inference from the view:
`movie_script` retains the NAME header and END-OF-LINE terminator, `chat` retains
the speaker prefix, and `narrative` uses the body. Existing canonical speaker
prefixes in view text are not duplicated. A malformed character source without
a colon cannot supply a speaker name; its selected view uses plain passage
formatting, never a header derived from reader prose. The token budget includes
formatting. Only ready text enters the result; explicit omissions and unavailable
views, including untracked historical passages, contribute nothing. Pending,
failed or stale passage views raise `GenerationCancelled` without reader fallback.
An unavailable or stale summary descends to fresh lower-level summaries or source
message views; it never contributes its reader text. Async
conversation and character editor callers first await the summarizer's existing
`ensure_perceptions` lifecycle, including its visible Retry/Cancel dialog. The
projection performs no model request and stores no cache across reads.

The projection walks backward and budgets the replacement text, stopping before
an entry would exceed the token budget or the returned-message limit. Hidden
messages are skipped unless requested. `before_message_id` excludes the revision
target and all later messages; a removed target cancels the read. Director guidance
is included only when requested and addressed to the viewing character. The
reader message objects and their formatting are unchanged.

`scene.context_history(perspective=character.name, stored_views=True, ...)`
selects this projection in perception mode, independently of the legacy
optional perspective filter. The converted conversation and editor templates
explicitly request stored views. `before_message_id` is rejected with `ValueError`
unless this gated, perspective-specific projection is selected; it never silently
returns later history. Best-fit expansion, minimum-dialogue backfill and reader
summaries cannot append raw prose to this actor path. The introduction enters only
through its recorded audience view. The projection chooses fresh
audience summaries for fully covered older spans, preferring coarser summaries
that fit, and keeps the unsummarized tail as message views. Spans crossing a
revision boundary are excluded. A span containing hidden messages or requested
director guidance descends to its sources so summarization cannot bypass those
filters. The projection may return less than the requested budget. Reader/author calls without a perspective and legacy
scenes retain their existing history assembly.

Character dialogue, add-detail, rewrite and unslop use the same history projection.
Repetition detection is author output: its corpus remains exact reader prose in
**every mode**, including passages with omitted/unavailable views, because model
paraphrases cannot establish lexical repetition. Comparison diagnostics can include
reader text for the author. Revision templates render only `text_a`, the candidate
being revised, never `text_b`, the earlier reader text used for matching. The
character revision's scene-history block still uses stored views.
Character unslop omits shared cached scene analysis until its producer supports
character audiences. Narrator/author revisions retain their broader context.

Passing `perspective` alone retains the legacy bucket-filtered reader assembly where explicitly used by legacy callers. Perception-mode offscreen-life narration, RAG input and the optional memory pass use the integrated viewer-specific paths documented in [Character memory retrieval](character-memory-retrieval.md).

Debug event `character_history.skip` identifies the message ID, viewer and
omitted/unavailable status when a passage contributes no text. It does not log
reader or perspective prose.

The integrated routes select evidence in code; semantic containment remains the generating model’s responsibility.
Viewer-scoped [retrieval](character-memory-retrieval.md) and [reinforcement/investigation history, direct inserts and generated-entry pins](reinforcement-investigation-perspectives.md) are integrated. [Snapshot](snapshot-perspectives.md) and [guidance/scene analysis](character-evidence-guidance.md) integrations also use stored evidence; other non-passage message types
are absent from this new history projection except scoped director guidance.
Scene description/story intention remain shared authoring inputs, and authored
sheets/details/world entries retain the user/director visibility responsibility.
The public creation opt-in is documented in [Saved scene format](scene-format.md#public-opt-in). Historical perception reconstruction is not supported.

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

## Audience summary generation and repair

`SummarizeAgent.ensure_summary_views(scene, summary_id, layer=0)` derives a base
summary from selected visible passage views, or a higher summary from
selected views in the immediately preceding layer. Base input reuses the projection's
message formatter to retain source speaker attribution even for unprefixed views.
Layer 0 means archived_history;
layer 1 means layered_history[0], matching SourceReference. Creation and explicit
regeneration finish reader clock and status updates before scheduling audience work.
Audience failures cannot abort reader finalization. The lifecycle uses the existing summarize /
summarize_events request shapes for audience outputs. Higher layers retain the
existing chunk splitting and reject empty chunks. Audience output retains short lines
and quotation marks; the reader-only minimum-line-length filter is not applied. No new analytical request kind
is added, and the shared scene-mode predicate controls the lifecycle.

Audience groups require exactly equal supported text and compatible exact source
references. Different audiences with identical text but independently addressed
dependencies remain separate. Presence in one event never grants a containing
reader summary. Explicitly omitted inputs contribute no prose but remain in
`sources` with their view identity and revision: changing an omission invalidates
its dependent summaries too. Ready and omitted summaries require terminal ready
or omitted dependencies; pending/failed records can retain non-readable
dependencies. An all-omitted input produces an omitted summary without a request.
An analyzed source with no view for a character contributes no text; its source-only
reference records that absence, so adding a view invalidates the partial summary.
Thus a character joining partway through a span can receive a summary of the portion
they know. A source with no analysis record, or a pending/failed assigned view, stays
pending and cannot produce a falsely ready summary.
Static or untracked historical entries are not reconstructed.

Audience summary prompts receive selected source prose, with no reader previous
summaries or global extracted facts. The source text includes established claims
and beliefs; prompt instructions preserve speakers, attribution and uncertainty,
and forbid inventing events or converting a reported claim into world truth.
The audience lifecycle explicitly passes `skip_author_hooks=True` at the request
boundary to bypass the dynamic-instruction and automatic-revision emissions;
passing `audience` alone does not disable hooks. Their producers do not yet carry
an audience. Configured archive instructions (base requests), explicit extra
instructions, scene intention/context, and generation-option writing style still
reach the templates as shared authored guidance. These inputs remain the author's
responsibility and are not converted to character knowledge by this step. Reader
summary calls keep their existing hooks. Base audience calls can return supported
facts in that same request, as described below. These constraints reduce exposure but cannot
guarantee that an LLM preserves every nuance; live prompt/output evaluation checks
attributed claims alongside deterministic orchestration and persistence tests.

Source changes use `perspectives_changed` and the existing transitive invalidation
contract. Fresh sibling views and unrelated summary branches retain their prose,
identity and revision. `repair_summary_views` queues individual audiences and processes compatible groups
from base to higher layers, generating only affected views. Pending input parks the
group outside the runnable queue until its sources become terminal; it does not
start a background snackbar or autosave on every turn. A cancelled branch is removed from
automatic retry; the shared cancellation handler consumes the scene cancellation
flag before its sibling groups continue, and an unrelated audience edit
does not restart its request or reset its failed status. Explicit
regeneration can retry that branch. Message-edit background
perception repair continues into summary repair; finalized perception work and
manual summary edits/regeneration schedule summary repair through
`schedule_audience_summaries`, which coalesces active work. These background tasks
leave the websocket receive loop available for Retry/Cancel responses.

Before publishing, the lifecycle rechecks the summary identity/range and exact
selected inputs after each request. Changed or removed sources discard the
response. Empty/failed responses leave a failed view and offer Retry; cancellation
keeps the reader output and permits only safe lower-level context. If a concurrent
edit changes the inputs, the discarded group is re-queued. Edits arriving during
repair are drained in batches bounded by `MAX_SUMMARY_REPAIR_PASSES`. Waiters are
checked after the last pass, and all repair entry points schedule remaining runnable
work. One retained background task drains those batches, including edits arriving
during autosave; projection uses safe sources until repair completes. Summary spans
are derived from persisted source IDs and their current message positions, so deleting
an uncited director or hidden message cannot widen a summary over its next passage.
Hidden messages are excluded from new summary inputs. At selection time, projection
checks that a summary actually covers the audience views currently requested within
its span. Required-view checks are lazy: only passages missing from a candidate
summary's coverage are selected, with each answer cached for the current projection.
The projection no longer preselects every historical passage. Coverage cache keys
include the character as well as the source and depth. Unhiding a message, or
requesting `show_hidden=True` after a summary was built without it, descends to source views where needed. This check also applies
through higher layers and requires no new visibility signal or saved schema. The
projection conservatively descends past existing summaries spanning hidden messages
unless `show_hidden=True`, and past requested director instructions. Selection checks
freshness synchronously with the existing indexed, depth-bounded read context. Save/reload preserves the existing knowledge
records and all dependency/view revisions; no separate summary schema is added.

Debug event `character_history.skip_summary` records the summary ID, viewer and
availability when projection descends to source views, without logging prose.


## Source-supported facts and scoped graph queries

In perception mode, enabled archive fact extraction runs in the existing base
**audience** summary request (`summarize(..., audience=..., return_facts=True,
skip_author_hooks=True)`). Reader calls publish complete summaries without reader
facts; layered calls add no extraction request. Explicit omissions add no facts.
The host supplies the audience from the selected view and ignores model `known_by`
claims. Previous-fact context is the intersection of evidence available to every
member of that audience, never the global fact list. Fact extraction remains off
when the existing Extract Facts setting is disabled. Legacy extraction/deduplication
keeps its existing behavior.

`Fact.contributions` is a tuple of immutable `FactContribution` records in
`talemate.knowledge.schema`. Each stores the exact source/view revision, audience,
acquisition order/time, extracted text, subjects, optional event `time_scope`, and
an optional accessible `supersedes` ID. A summary contribution uses the latest
ready input acquisition as its conservative span-end learning bound, not the time
archiving happened. Creating an old archive later cannot reorder it after a newer
disclosure. Facts within the same span share that bound; event-time distinctions
remain explicit in their prose and `time_scope`, without inferred timestamps.
Message/summary contributions require a
specific view ID and revision. Disclosure contributions reference the independent
disclosure itself. These are derived snapshots: saved perspectives and disclosures
remain the durable evidence, and no learning record depends on a disposable fact ID.
Old facts omit this field when empty; old scenes need no reconstruction.

`replace_source_facts(scene, batches)` accepts `(source_reference, audience,
parsed_facts)` batches, validates all source views before publication, and replaces
only those source/view contributions. Contributions from other passages, summaries
or disclosures survive even when they share a combined fact. Valid empty extraction
removes only the requested contribution. Source changes use `perspectives_changed`
to prune stale evidence and refresh the affected memory documents in the existing
background lifecycle. Sibling views and unrelated branches are not re-extracted.
Removing an audience member preserves the other recipients; renames follow audience
names without rewriting historical prose. Reset, Reset Scene State with history
wiping, and progress-reset exports discard the source-derived index as well as its
sources, retaining authored facts. Progress-retaining saves/exports preserve both.

The new path combines only exact whitespace-normalized text and identical subject
sets and time qualifiers from the same source. Equivalent views of that source can
combine; different sources stay separate even with the same explicit ISO date or
timestamp. A calendar date identifies neither an occurrence nor a shared event.
The prompt example requests `time_scope` with a null case and omits model-assigned
audiences. Dates must be literally supported in both extracted text and extraction
input; an unsupported normalized date drops only the optional scope (with a debug
log), preserving the fact and its source-local identity.
Acquisition time is not event time;
"holds the key" versus "held the key", attributed claims versus observations, and
uncertainty qualifiers remain separate. Embeddings do not authorize a merge;
this conservative implementation does not need candidate search for its exact
lookup. Uncertain semantic matches remain separate with no verification LLM call.
The shared contract intentionally adds no belief engine or confidence score:
structural checks and exact matching cannot prove the model preserved every
semantic qualification. The extraction prompt forbids invented events and requires
attribution, uncertainty and established beliefs to survive; live evaluation and
regression tests exercise those requirements without claiming a semantic guarantee.

`SummarizeAgent.rebuild_supported_facts(scene, sources=None)` rebuilds from saved
views/disclosures, including when all fact IDs were discarded. Passing source
references limits requests and replacement work to those sources; a reference with
`view_id` limits it to that view. Full explicit rebuild enumerates base summaries,
uncovered saved passage views and independent disclosures. Coverage is tracked per
concrete view revision and audience member, and only ready summary groups cover
passages. Failed or pending summary groups leave ready passage evidence available
for direct extraction. Full rebuild skips pending or failed passage views too;
explicitly requesting such a view still fails instead of publishing a successful
rebuild. Ready and omitted views remain eligible. A partly covered shared passage view is
extracted for its whole audience. Base extraction reads
the summary's saved source views by ID, preserving speaker formatting, rather than
stale positional archive ranges. It does not reconstruct missing historical views.

All requested results are staged and revalidated against current revisions before
replacing the index. Missing/malformed extraction or a changed source returns
`failed` with visible Retry/Cancel; it cannot publish a successful partial rebuild.
An explicit empty source list or disabled extraction returns `None`. A valid empty
FACTS list is successful. A valid audience summary remains ready when its FACTS
block fails; only facts are marked failed, with visible retry. A later successful
sibling summary does not clear that failure. Both the fact-failure dialog and
explicit fact regeneration retry saved summary groups without replacing their prose, view identity, revision or dependent views.
The dialog pins the concrete published view before waiting; if that view disappears
or changes while the dialog is open, Retry stops without requesting sibling views.
Successful rebuilds update the persisted base entry's `facts_status` as well as
runtime audience failures, so a save/reload or later summary check cannot resurrect
a repaired failure. A partial audience repair keeps other failed groups marked.

Equivalent replacements preserve fact IDs, including unchanged local rebuilds.
Canonical author edits are preserved when contribution sets match, even when a
single-view replacement changes the order of two equivalent contributions.
Removed facts lose incoming knowledge edges and supersession references in both
canonical records and contributions. Publication rejects self-links and cycles
across both forms of supersession, preserving existing valid links first.
Memory I/O errors report failure even if the canonical source-supported index was
already installed. Pending upserts and deletions remain in the per-scene dirty
queue until written, including retries of an already-empty extraction. The mirror
serializes writes and drains changes queued during I/O. Switching scenes pauses
this work with its keys retained rather than raising a generation cancellation;
resuming that scene can drain its queue. The existing background `regenerate_facts` route uses this operation for
one base entry, keeps reader prose intact, and reports its actual `facts_status`.
Async callers must run rebuilds off the websocket receive loop so retry responses
can be dispatched. No new public mode or request kind is introduced.

Local rebuild cost is limited to changed/requested source audience groups: one
existing summary request per group, without regenerating unrelated summaries or
replaying a scene's learning history. Source indexing, exact-match lookup, and
selection checks still scan stored records; this is not a constant-time graph
index. Background invalidation updates affected fact documents and preserves
independent contributions. Full-scene extraction occurs only when explicitly
requesting a full rebuild.

`facts_about`, `current_state`, `relationship_timeline` and `superseded_chain` in
`talemate.knowledge.graph` accept an explicit `character` argument. Omit it for
existing global author queries, including author-marked false records. The Current State and Relationship Timeline nodes
also expose an optional character input; an empty string means the global query.
`superseded_chain(character=...)` rejects legacy mode with `ValueError` instead of
silently returning an unscoped chain. `bucket(scene, character)` is scoped.
In the new mode these queries select current supporting contributions before
entity matching and return that character's text and acquisition evidence only.
A global author correction, `false` flag, or inaccessible superseding update cannot
replace their last-known evidence. A later witnessed update carries its own time
and order; disclosure time stays independent of its historical provenance. Hidden
passages are excluded through their derived facts too. Facts without supported
contributions are absent from this scoped derived index. Authored entries use visibility,
explicit learning uses disclosures, and character retrieval uses audience records.

Known limits: facts acquired from one source share its acquisition
order. Ties retain extraction/insertion order; the model's list is not a finer
verified event chronology. New-mode fact updates prune obsolete topic membership
but do not recluster topics in this path. Neither limitation changes the source
contribution boundary.


## Explicit grants and disclosures

`knowledge.disclosures.grant_disclosure(scene, character, target, text=..., whole_entry=False)` uses the canonical entry classifier and the same offered target set as the Knowledge tab before creating a `Disclosure`. Partial grants require nonblank supplied text and retain it verbatim, even if the source value is non-textual. Only whole-entry copying requires textual source content. Store collisions follow the existing classifier precedence; description paragraph IDs fold onto their entry. An explicit whole-entry request snapshots the current entry text. Empty, removed and unresolved targets are rejected before any acquisition counter, disclosure or edge changes. These are author assertions; the grant performs no semantic inference and invents no dialogue. Director routing remains model-mediated and subject to its normal write confirmation.

`Disclosure.origin` records the selected entry ID as historical provenance, including authored entries and disposable fact IDs. When the selected source has a perspective revision, `provenance` also retains that SourceReference. Neither grants access to the origin nor acts as a computational dependency. The independent disclosure reference is what downstream summaries and fact contributions cite.

`Disclosure.message_id_boundary` stores the greatest existing scene-message ID at creation (zero in empty history). IDs already have a monotonic allocator; reload advances it beyond saved disclosure boundaries even if the boundary message was deleted. `disclosure_positions` places each record after surviving history at or below that boundary. The existing `acquired.order` breaks ties between disclosures, while `acquired.ts` records story time. The boundary is required; this unreleased format has no migration for boundary-free foundation records. No message is inserted and reader history remains unchanged.

`project_character_history` inserts only the viewer’s disclosures, counts their tokens, respects revision prefixes, and avoids both skipping and duplicating disclosures when using summaries. Base summary inputs interleave disclosures before the subsequent passage, never into an archive wholly preceding their acquisition. Layered summaries inherit their references and prose from base views. A ready summary missing a required disclosure is bypassed for safe source views. Perception’s established-knowledge context uses the same message boundary to avoid backdating a grant during delayed analysis.

The GrantKnowledge node and author websocket action share target validation. The author handler runs in the background so optional fact-extraction retry dialogs leave the receive loop available; it reports the disclosure before indexing and saves once after indexing finishes. Both pre-indexing and post-indexing `character_knowledge` frames echo the grant’s `request_id`; the tab completes a disclosure submission only for its matching frame, so a late indexing refresh cannot clear a later request. Rejected requests emit the normal correlated operation failure. The tab refreshes after indexing and shows failed extraction status. Both use `rebuild_supported_facts` with the independent disclosure reference, under the existing extraction setting. No new request kind or fact identity scheme is introduced. Extraction failure retains the disclosure and is not reported as a successful fact rebuild. The original source can be regenerated without replacing the disclosure contribution. `knowledge_changed` identifies the disclosure itself; its label is the selected text, never the containing archive.

User-facing partial/whole wording is documented in the Knowledge guide. The shared mode predicate remains the only eligibility check; legacy grants keep their edge semantics.

The director module uses Grant Knowledge Metadata and Grant Knowledge Confirmation adapters over the existing focal metadata and string formatter. Both select their content using the shared mode predicate: legacy examples and confirmations remain unchanged, while perception grants show selected information and the whole-entry choice. The character report labels disclosures and restricted entries separately and retains supplemental grants and recorded-fact coverage. Revokes and topic-awareness assertions are legacy-only.


## Searchable effective audiences

In opted-in perception scenes, `knowledge.memory.audience_documents(scene)` builds a derived character index in the existing memory collection. It reuses `select_character_view`, `character_fact`, independent disclosures and authored `EntryVisibility`. Ready audience views replace reader prose; hidden, pending, failed, omitted and unsupported content is not indexed for characters. Fact documents use each character's supported wording, preserving last-known evidence despite a different author correction. Authored sheets, world entries and static history follow their author-managed visibility. An event known to the entire current cast is still audience-limited, not common lore for future characters. Legacy edges do not authorize these records.

Canonical reader/author memory documents remain available. Managed character variants have derived `knowledge:` IDs and the following metadata:

| Field | Meaning |
| --- | --- |
| `knowledge_index` | `True` for managed character documents; `False` for canonical author records. Existing new-mode canonical records are marked during reconciliation. |
| `knowledge_common` | Full indexed text is available to everyone under authored visibility. |
| `knowledge_audience` | Nonempty string array of viewers supported for the full indexed text. The subject/owner `character` field remains a separate restriction. |
| `knowledge_source` | Source identity for the derived variant; source kind/layer, revision and acquisition order/time accompany narrative records. |
| `knowledge_id` | Canonical source/entry ID used by scoped ID lookups; multiple derived variants may represent it. |
| `knowledge_fingerprint` | Internal reconciliation digest. Unchanged documents are not re-embedded. |

`await memory.get(query, viewer="Elmer", **restrictions)` performs one Chroma similarity query over managed records satisfying **common OR audience contains Elmer**, ANDed with every existing metadata/subject restriction and the pin-only exclusion. Unknown viewers or a viewer supplied outside perception mode are rejected. Ordinary author `get` and metadata lookups retain canonical records without character duplicates. [Character memory retrieval](character-memory-retrieval.md) documents projected RAG inputs, scoped entity/topic additions and ID lookups, AI retrieval and cache validity.

Chroma 1.5.0 or later is required for array metadata and `$contains`; the project lock uses 1.5.9. Real temporary-collection tests exercise the metadata union and replacement behavior. Empty metadata arrays are invalid. Audience replacement removes obsolete managed variants before writing their replacements, so old recipients cannot survive a metadata merge. If an index write fails, dirty state is retained and an explicit scoped read must successfully synchronize before it can return results; query errors propagate rather than masquerading as an empty successful result. Author queries log synchronization failures and continue querying canonical records using `knowledge_index != True`, which includes unmarked rows written before the gate was enabled even if the first reconciliation fails, while excluding managed character variants.

The memory agent uses `event.affected` to rederive changed sources and their supported facts, retaining indexed source associations even when another event listener has already pruned the live facts. Canonical writes refresh their authored, summary or fact groups without rederiving unrelated views. Before reusing cached records, synchronization also checks the current source map: message or summary groups removed without notifications, including truncated layered history, are dropped along with their unsupported fact variants. Full derivation is reserved for initialization, reconciliation and broad invalidations such as cast changes, perspective resets, visibility edits and deletions. Background updates coalesce changes; scoped reads wait for them and retry if the scene's index revision changes during a query. A scene/collection switch discards the operation instead of writing to or returning the next scene's data. Direct index calls refuse writes while memory is readonly or its collection is not ready; dirty work remains for a later retry.

`await memory.rebuild_audience_index()` reconstructs managed records from scene sources; `Scene.commit_to_memory` includes it. Initialization reconciles a reopened new-mode collection, including stale persisted variants, and marks pre-existing canonical rows without removing their other metadata. Rebuilding does not reconstruct legacy knowledge or add an LLM request.
