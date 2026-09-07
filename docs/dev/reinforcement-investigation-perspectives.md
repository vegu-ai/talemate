# Reinforcement and investigation perspectives

In opted-in perception scenes, reinforcements and context investigations use the same summarizer-owned analysis as character and narrator passages. This is the K10 integration; the shared `character_knowledge_enabled(scene)` gate controls it. Legacy scenes retain their existing behavior and request counts.

## One source, one analysis

Sequential reinforcements and investigations finalize through `Scene.push_history`. Non-sequential reinforcements persist a `ReinforcementMessage` in the reinforcement's optional `perspective_source` field. Those messages use the existing message source identity, `SourcePerspectives`, acquisition order, provenance, revisions and retry contract, without being appended to history.

Each changed non-sequential answer receives a fresh source with current presence and acquisition time/order; changing a direct answer through the state editor also replaces its source. The prior source is retired and its dependents invalidated. Re-running or retrying the same non-sequential answer keeps its ready views, source and original acquisition boundary without another analysis request. The `never` insertion mode also analyzes each changed answer, because its generated entry remains available to retrieval. This adds an audience-analysis request even though no direct insert is rendered.

`SceneMessage.perception_text` includes the complete reader heading/question and answer for these two message types. Editing either invalidates the source. Character view formatting uses the complete replacement alone; it never adds the original reader heading back. Other passage types keep their existing formatting.

The shared analysis receives relevant audiences and prior evidence. A reinforcement is author-maintained state, not speech or a discovery event. An investigation may be reader-only and produce omissions for every character; supported in-world action can establish learning. `passage.sub_type` identifies the reader operation (`query`, `visual-scene`, `visual-character`, `examine`), and `subject_character` identifies the subject of a character description. Neither field identifies an initiating investigator: the visual-character handler describes its target, while the examine handler expands a world-state entity snapshot. A query can describe either reader-only information or an actual in-world event, so subtype alone cannot decide discovery. The shared analysis assesses the supplied events under D14; naming a character in a title or listing them as present does not establish access.

## Direct inserts and generated entries

Use `reinforcement.context_for(scene, viewer)` for a character-facing insertion. It selects the stored view and checks authored visibility. Omitted/unavailable audiences and missing passages produce no text, with missing-source diagnostics. Pending, failed or stale required sources stop generation with `GenerationCancelled`. Calling without a viewer retains the complete author text. Common and visual context templates omit empty inserts and pin separators as well as hidden prose.

Automatic detail/world-entry writes retain complete author text and preserve authored visibility. They store a `ReinforcementEntry(source_id=...)` association on the entry itself: `ManualContext.reinforcement` for world entries and `Character.reinforcement_entries[detail_name]` for details. A generated entry temporarily without a passage carries `source_id=None`; its character-facing representation is omitted until a later generation writes a new association. No association is inferred from a tracker's question. An unanswered tracker therefore leaves a pre-existing authored entry alone.

The character-facing generated entry uses the associated source replacement, intersected with its authored visibility. Its full answer is never promoted to common lore just because its visibility is `everyone`. The source association survives an orphaned tracker, but deletion removes it with the entry. Ordinary authored writes through `set_detail`, `set_detail_defer`, `save_world_entry` or `update_context_db_entry` detach the association only when the text changes; metadata-only saves keep the projected audience. Reusing a deleted entry's name does not inherit a restriction. Character renames update the live tracker and source metadata, while detail associations remain under their detail keys and world questions remain unchanged.

Shared world entries and character details export authored text and visibility without scene-local reinforcement associations. Importing shared data cannot resolve a foreign message ID against the receiving scene. Syncing unchanged text back to an existing local entry preserves that scene's own association.

Generated entry headings and technical context IDs may contain the original question. Character-facing pin and memory templates render the selected prose without those raw labels. Canonical author ID reads retain full stored text. Generated details are excluded from analytical authored background so they cannot justify their own learning. Other authored entries retain their existing visibility policy.

## Updates and recovery

Generated entries are written alongside the new author answer before perception analysis, so a blocked pass cannot leave their canonical versions out of step. View events invalidate authored projections only when their affected sources include a generated entry's associated passage. Direct insertion reads the current stored view on every render. Source deletion and mode changes omit missing passages rather than stopping unrelated prompts; pending, failed and stale sources remain blocking. Index skips log the entry, viewer and failure state.

History and direct sources share one ordered merge for perception processing and context selection. Unchanged direct sources are neither rewritten nor rebound on each analysis iteration. A changed answer received during an analysis retires that source and registers the replacement; stale model output is discarded.

Stored direct sources are bound after world-state loading and advance the message counter before any new message can be allocated. Orphaned entry associations also reserve their message IDs so a later passage cannot inherit their identity. Failure uses K03's pending/failed state and Retry/Cancel/Ignore behavior. Reader text remains stored; character generation never falls back to it. A retry does not retroactively acquire later evidence or disclosures, while a changed answer uses its new acquisition point.

The existing snapshot request generates [audience-targeted snapshot content](snapshot-perspectives.md) under K11. Broader director/guidance integration remains a separate step.
