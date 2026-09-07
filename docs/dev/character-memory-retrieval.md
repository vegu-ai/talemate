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

Topic supplementation caches the viewer’s eligible fact variants, vectors, sorted members and centroids per index revision, collection generation and topic membership. Each query embeds only its text and compares cached centroids before the per-topic cutoff. Cached source text is formatted against the current scene time when returned or passed to a caller filter, so advancing time updates relative ages without refetching facts or rebuilding unfiltered centroids. Arbitrary caller filters reuse the fetched variants/vectors but narrow them before deriving centroids. It neither fetches canonical prose by fact ID nor uses another character's facts to select a topic. Last-known fact text and restatement metadata come from the supported variant, preserving the source-supported fact contract despite a different global author correction.

AI retrieval templates and the optional memory pass receive projected history, eligible retrieved text and visibility-scoped authored character records. Shared reinforcement, pin and dynamic-instruction inserts are not added to character retrieval requests. Reinforcement and investigation sources now have [stored audience views](reinforcement-investigation-perspectives.md); broader guidance integration remains a separate step, and these requests do not infer new learning from those shared inserts.

## Cache and failures

Perception character cache identity is a digest of the viewer, monotonic collection generation, audience-index revision, retrieval settings (including distance cutoff and direction mode), query-history size and topic membership. The cache dictionary is scene-local. Both direct and AI retrieval use it when caching is enabled. Direct retrieval outside perception character scope remains uncached, including author calls in perception scenes, so memory edits appear even when history has not advanced. View/disclosure changes, source removal, visibility changes and index rebuilds invalidate the corresponding cached generation. Explicit goals, raw author overrides and retrieval-method overrides bypass the shared cache. A result computed during an index change cannot populate the new revision's cache.

Scoped multi-query and RAG operations synchronize the index and allow at most one repeat if relevant state changes while they await retrieval or the model. A single RAG wrapper covers query generation plus the optional memory pass. Repeated changes fail closed with a retryable error; a generation whose revision changed is not written into the cache. A scene/collection switch rejects the operation. Author similarity and metadata reads retain the canonical fallback described in the audience-index documentation, including unmarked records when initial reconciliation fails.

Inside a prompt with `memory_viewer`, both `query_memory` and `retrieve_memories` pin backend retrieval to that viewer. `retrieve_memories` derives its input from the viewer projection instead of its supplied author lines. An explicit `viewer=None` on `query_memory` cannot remove the enclosing character scope.
