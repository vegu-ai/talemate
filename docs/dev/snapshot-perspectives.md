# Audience-targeted snapshots

K11 adds audience replacements to the existing world-state snapshot request. It is active only when `character_knowledge_enabled(scene)` is true: the internal environment gate and the scene's perception eligibility must both allow it. Legacy scenes keep the existing request shape and rendering. There is no new public setting or additional awareness request.

## Generation and evidence

`snapshot_audience_context(scene, budget, focus_text)` gathers fresh, ready source perspectives and explicit disclosures for active characters and canonical characters named in the current focus. Inactive, unmentioned characters do not consume the evidence budget. It takes recent evidence within a per-character token budget, with at most twenty records per character. The snapshot request receives this evidence alongside its complete reader context. The generating model is instructed that reader-only discoveries, new flavor, mere presence and the existence of an entity cannot establish character awareness.

Each entity response adds `views`; the separate location string adds `location_views`. The model is asked to cover every supplied character exactly once. The host treats missing or malformed assignments as omitted for the affected audience, while retaining independently valid assignments. Unknown names reject their assignment; duplicate names omit that audience. A ready assignment has `audience`, `status: ready` and `text`; an omitted assignment has `status: omitted` and `text: null`. Multiple audiences can share an assignment, but the host stores separate records with each character's evidence.

The text is a complete display replacement, including any safe name, emotion or location. For example, the reader snapshot might say that Bob has a bandaged arm and privately plans an escape. Alice's view can retain the bandaged arm without the escape plan; Bob's view can include his plan if his established perspective supports it. A secret-bearing item name must also be replaced, rather than being prepended to otherwise safe prose.

The host checks assignment shape and audience identity, rejects model-assigned source references or digests, and checks evidence presence and freshness. It attaches the references supplied in the request and a digest of the canonical name, snapshot and emotion (or the location string). If evidence changes during generation, affected ready assignments become pending. These checks do **not** establish that the generated text follows from its evidence: semantic support and private-content containment depend on the generating model's compliance. A well-formed ready assertion can pass host checks even when its content is unsupported. There is no separate awareness request or semantic verifier.

## Stored fields and durable updates

Character, item and place records optionally carry `perspectives: SnapshotPerspectives`; the world state optionally carries `location_perspectives`. Each contains `content_digest` and existing `PerspectiveOutput` records. Missing metadata is omitted from serialization. Loading validates canonical audience names; renaming or deleting a character clears snapshot classifications for the next normal refresh.

The existing durable merge also applies audience changes:

- Supplying a snapshot or emotion replaces its classification in the same merge. Missing or invalid `views` clears the old classification rather than applying its audience to new text.
- Supplying only `views` replaces the audience assignments for unchanged content. Omitting an entity or changing only highlight mentions preserves its existing classification.
- A location change clears its classification unless matching `location_views` accompany it. Entity deletion, eviction and scene cuts remove the corresponding metadata.

Wholesale snapshot mode requests complete reader fields and views for every retained entity; omitted entities are removed. If a named existing entity arrives with only views, the host preserves its prior reader snapshot so a partial model response does not erase it. The separate location field still changes only when supplied. A malformed location keeps the prior reader location but clears its classification and discards the accompanying views.

## Prompt rendering and freshness

`scene.world_state.snapshot_for(viewer)` returns projected location and lists of complete character, item and place strings. Calling without a viewer returns the reader representation. The common snapshot template passes only `knowledge_viewer` and retains the existing optional **Pin to context** toggle. Narrative viewpoint/tense variables do not identify an audience.

For character calls, the renderer verifies the content digest and every attached source with `can_cite_view`. Missing, pending, failed, omitted or stale views contribute no text; it never substitutes reader fields or appends their raw labels. Source edits, deletions, history resets and disclosure revocation therefore hide dependent content without an extra analysis request. The reader snapshot stays available.

Evidence attachment is conservative: every source shown for that viewer is attached to its replacements, so changing one can hide an otherwise unaffected replacement. Recovery requires a later response to include that entity with fresh views; an ordinary refresh does not guarantee this. Durable omissions retain stale metadata, including indefinitely when eviction is disabled; eviction removes the entity without guaranteeing its re-addition. A limited evidence budget can also omit information a character knows. Optional context is omitted in these cases; snapshots do not become new learning sources or acquisition events.

See [character perspectives](character-perspectives.md) for source freshness and [reinforcement and investigation perspectives](reinforcement-investigation-perspectives.md) for other world-state inputs.
