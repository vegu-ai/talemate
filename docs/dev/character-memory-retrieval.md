# Character memory retrieval

Character retrieval in opted-in perception scenes uses persisted views and disclosures for query inputs, and the [effective audience index](character-perspectives.md#searchable-effective-audiences) for candidates. The shared `character_knowledge_enabled(scene)` gate controls this path. Legacy scenes keep their existing retrieval behavior.

## Character and author inputs

```python
await conversation.rag_build(character=elmer)
await conversation.rag_build(
    character=elmer,
    sub_instruction="Find a safe route home.",
    retrieval_method="queries",
)
await summarizer.rag_build_for_author(
    prompt=author_analysis,
    sub_instruction="Explain the unresolved conflict.",
    retrieval_method="questions",
)
```

`rag_build` takes no raw prompt/history override. For a character, it derives recent semantic queries and entity-name requests from `project_character_history`, including that viewer's disclosures. Configured query/question generation uses the same projection with its normal larger token budget. Missing/omitted views contribute no reader fallback; pending or failed required views block retrieval under the projection contract. Changing another character's private text cannot inject it into these query inputs. A real disclosure can change them.

`sub_instruction` is a **goal**: callers may supply authored or director guidance, never excerpts of shared history or an omniscient analysis disguised as a goal. Goals do not establish knowledge. Raw scene-context overrides belong to `rag_build_for_author`. Its optional `character` argument is accepted only in legacy scenes, where it preserves the character's bucket filter, analysis viewer and optional memory pass. Passing a perception character raises `ValueError`; use `rag_build` for that character. A call to `rag_build` with no character retains author scope with internally assembled history. The common memory template routes perception character calls without a raw override. In legacy scenes, an explicit `memory_prompt` retains raw input and forwards `talking_character` when present; author overrides without a character remain available in either mode.

Semantic queries retain the viewer’s own stored director messages; the optional memory pass keeps them unless live director guidance replaces them. Their formatting follows the director’s configured direction mode. The larger AI query/question context keeps director messages excluded, as its existing author path does. Retrieval uses K04’s hard token budget; the old `min_dialogue` and `sections` kwargs are ignored by the shared history builder and do not create a dialogue floor.

Perception retrieval does not depend on the legacy perspective-filter toggle. Character identity remains explicit throughout the operation. Direct semantic retrieval adds no LLM request; the configured queries/questions methods and optional conversation memory pass retain their existing request counts.

## Eligible candidates

```python
await memory.multi_query(["harbor tides"], viewer="Elmer", limit=10)
await memory.get_documents_by_meta(
    {"character": "Marie", "typ": "base_attribute", "attr": "description"},
    viewer="Elmer",
)
await memory.get_document("F12", viewer="Elmer")
```

The viewer condition remains inside Chroma: managed records whose full text is common OR includes the viewer, combined with metadata restrictions and pin exclusion. The candidate cutoff therefore applies to eligible memories. Custom result filters may narrow that set; similarity cannot rescue rejected access in perception mode. Recency, diversity and optional cross-encoder ranking remain available.

`knowledge_id` identifies the canonical source/entry represented by a managed variant. A viewer-scoped ID lookup accepts source/entry IDs and returns a dictionary keyed by the matching **derived** document IDs; unknown or inaccessible sources return no rows. Several audience variants may share one source ID. Omitting `viewer` retains the canonical author ID lookup. Entity descriptions use scoped metadata lookup and their original paragraph order.

Topic supplementation caches the viewer’s eligible fact variants, vectors, sorted members and centroids per index revision, collection generation and topic membership. Each query embeds only its text and compares cached centroids before the per-topic cutoff. Cached source text is formatted against the current scene time when returned or passed to a caller filter, so advancing time updates relative ages without refetching facts or rebuilding unfiltered centroids. Arbitrary caller filters reuse the fetched variants/vectors but narrow them before deriving centroids. It neither fetches canonical prose by fact ID nor uses another character's facts to select a topic. Last-known fact text and restatement metadata come from the supported variant; an author edit of the record's text (`Fact.text_edited`) replaces the text for every viewer, while the `false` mark stays an author judgement and each viewer's chain follows their own contributions.

AI retrieval templates and the optional memory pass receive projected history, eligible retrieved text and visibility-scoped authored character records. Shared reinforcement, pin and dynamic-instruction inserts are not added to character retrieval requests. Reinforcement and investigation sources now have [stored audience views](reinforcement-investigation-perspectives.md); broader guidance integration remains a separate step, and these requests do not infer new learning from those shared inserts.

## Cache and failures

The scene-local cache uses stable slots selected by the retrieval settings and viewer. Each published entry records the exact pre-reply history boundary plus a digest of the eligible source records at that boundary. The boundary includes retrieval-visible message text, knowledge revision and hidden state. Message-bound facts whose message is later than the boundary are excluded. A viewer's knowledge dependency includes only that viewer's edges and excludes edges tied to the transient reply being replaced; deleting or wiping an older source detaches retained edges from that source so they continue to count. Viewer-less retrieval does not depend on knowledge edges because it does not apply that filter, but it does track the unprojected scene introduction used by early history context. Unrelated archive, fact, authored-entry and visibility changes remain part of the applicable source digest. All entries record the memory collection generation, while character-scoped entries also record source-aware topic membership. Audience source digests are keyed to the revision that produced the in-memory document snapshot, so a concurrent index rebuild cannot validate stale documents under a newer revision. Source digests are reused within the same collection/source revision so publish and refinement validation do not repeatedly scan the store. Both direct and AI retrieval can publish in character scope. Direct retrieval outside character scope remains uncached, including author calls in perception scenes. Explicit goals, raw author overrides and retrieval-method overrides bypass the shared cache. A retrieval already in progress can finish with its earlier context. A result built before an applicable input changed is not reused after the change.

Scoped multi-query and RAG operations synchronize the index and allow at most one repeat if relevant state changes while they await retrieval or the model. Cache lookup, query generation and the optional memory pass all remain inside that operation, so a hit cannot bypass the audience-index guard. Repeated changes fail closed with a retryable error. A scene/collection switch rejects the operation. Author similarity and metadata reads retain the canonical fallback described in the audience-index documentation, including unmarked records when initial reconciliation fails.

Inside a prompt with `memory_viewer`, both `query_memory` and `retrieve_memories` pin backend retrieval to that viewer. `retrieve_memories` derives its input from the viewer projection instead of its supplied author lines. An explicit `viewer=None` on `query_memory` cannot remove the enclosing character scope.
