# Knowledge

## Character perspectives (opt-in)

When creating a **New Story**, enable **Character perspectives** to use audience-specific character context. The choice is **off by default** and applies to that new story before play. **World Editor → Scene → Settings** shows the current mode. Saves, reloads and forks preserve it. **Scene → Shared World → New Scene** also inherits the current mode for the next episode, with the mode shown before creation. Existing stories and character-card imports keep legacy behavior; resaving or resetting does not reconstruct their past perceptions. Start a new story to opt in, then add your characters and world entries.

The reader keeps the complete prose. Characters receive stored replacement views of passages, audience summaries, disclosures and accessible memories. Missing or failed views never substitute the reader's private text. Narration and author planning can retain broader reader context; character guidance and analysis use the character evidence appropriate to their task.

### Cost and recovery

The Summarizer runs an extra analytical request after each finalized character, player or narrator passage, covering relevant audiences together. Investigations and changed tracker answers also use this analysis, including trackers that never insert a history message. Repeating an unchanged tracker answer reuses its source. Audience summaries and enabled fact extraction add work as material is summarized or rebuilt. This mode replaces the legacy learned-this-turn request; it does not run both learning passes. The optional AI memory pass remains a separate opt-in.

While analysis runs, dependent character generation waits. If it fails, the generation error dialog offers **Retry**. Cancel or Ignore stops the dependent generation without falling back to reader text. Correct the source or client configuration and retry generation to rebuild pending views. Edits invalidate dependent views and caches; stale in-flight results cannot replace the edited source. A cancelled fact extraction retains the underlying perspective/disclosure; the Knowledge tab reports failed disclosure indexing. Rebuilding supported facts can recover its index later.

Perception uses the generating model's common-sense interpretation, not a proof of what a character understands. It must not invent an observation or event to justify knowledge. Clean inputs do not guarantee that a model will never invent an action, explanation or lucky guess.

### Author responsibilities

Keep secrets out of **scene description** and **story intention**: these remain shared authoring inputs. Set visibility on character sheets, details and world entries yourself or through the director. Do not put private instructions into a character's shared description and expect perception to remove them.

In this mode, the separate learned-this-turn ledger, secret-valued absence warnings, topic all/some/nothing assertions, similarity-based access rescue and knowledge revokes are retired. Legacy controls for presence filtering, absence, topic assertions and learning are hidden while this mode is active. They remain available when a legacy scene is loaded. There is no forget/amnesia operation. Restricting an authored entry is not erasure of an already acquired disclosure.

## Visibility

Character descriptions, attributes, details and world entries have **Known by** settings:

- **Everyone** (default): common authored information.
- **Only the owner**: available to its character owner; a world entry has no owner.
- **Specific characters**: available to the owner and listed characters.

Set visibility in the Characters or World tab. It governs authored inputs, pins and retrieval. Generated reinforcements also need a current audience view; visibility alone cannot expose their withheld full answer. The director's `set_known_by` uses the same visibility settings and normal write confirmation.

## Explicit disclosures

In a perception scene, **Characters → Knowledge → Establish character knowledge** gives a character selected information now. Select a **Source entry** and enter **Information to disclose**. **Give selected information** copies only that text into durable knowledge; it does not unlock the containing archive or imply the character was present earlier.

**Give the whole entry** is off by default. **Give all entry content** explicitly copies all current source text, including private details. Neither choice grants access to future edits. Invalid sources and unknown characters are rejected before content is added. Earlier perspectives stay unchanged; the disclosure appears in subsequent context and survives saves, source edits and fact regeneration.

This is author establishment: no dialogue or discovery event is invented. The director's `grant_knowledge` uses the same operation, with `information` for selected text or explicit `whole_entry: true`. Supplemental grants can be removed, but removal does not erase a disclosure. Revokes are unavailable in this mode, including node and API writes.

When enabled, fact extraction indexes the disclosure. The disclosure survives extraction failure; retry the failed request or use a supported-facts rebuild. See the [developer guide](/talemate/dev/character-perspectives/) for the rebuild API.

## Topics and coverage

The memory agent groups recorded facts into [topics](/talemate/user-guide/agents/memory/settings/#topics) using embeddings, without an LLM request. The Knowledge tab's **Recorded-fact access** table counts accessible facts out of recorded facts in each topic. In perception mode, only facts with current supporting audience evidence count. Pending or invalidated support does not count. This measures access to the index, not understanding or exhaustive world knowledge. Topics remain useful for retrieval and author inspection; characters receive no all/some/nothing topic assertions in this mode.

## The director

The director can inspect full author records, visibility and character disclosures. Its **Character Knowledge** query lists disclosures, supplemental grants, restricted authored entries and recorded-fact coverage. Character-targeted guidance must respect established evidence. Normal author planning may use broader context.

## Facts in node graphs

[Knowledge nodes](/talemate/user-guide/node-editor/reference/nodes/knowledge/) provide **Facts About**, **Current State**, **Relationship Timeline**, **Entry Knowledge**, **Character Knowledge**, **Set Entry Visibility**, and **Grant Knowledge**. In perception mode, fact queries use supported character contributions and Grant Knowledge creates a disclosure. **Revoke Knowledge** rejects perception scenes before mutation. Legacy graphs keep their existing grant/revoke semantics.

## Retrieval

Perception-mode character retrieval derives queries from projected history, then ranks within eligible audience records. Similarity ranks relevance; it never grants access. The optional [AI memory pass](/talemate/user-guide/agents/conversation/settings/#ai-memory-pass) rewrites already scoped memories. See [memory settings](/talemate/user-guide/agents/memory/settings/#retrieval) for recency, diversity and local reranking.

## Legacy scenes

Legacy operation remains available and unchanged. Characters' access is derived from presence, ownership, authored visibility and grant/revoke edges. Unknown historical presence is shared. The conversation history filter replaces missed spans with a gap; layered summaries use their coarse presence. Narrator, director, summarizer and world-state author requests retain the full record.

### What the speaking character gets

Legacy conversation settings control presence filtering, a secret-valued absence block, topic awareness assertions and optional AI memory rewriting. Reinforcements and investigations retain legacy insertion behavior. The optional learned-this-turn ledger still assesses recent existing facts and writes inferred grants. The similarity knowledge gate can rescue presence-rejected retrieval results; it cannot override visibility or a revoke.

### Grants and revokes

The legacy **Knowledge** tab lets you choose an entry, **Grant** or **Revoke**, and an optional note. Typing in the Entry autocomplete does not select a result. Manual edges have source `manual`; director writes use `director`; summary learning uses `told`; the optional ledger uses `inferred`. A revoke takes precedence over a grant. Removing an edge retains the underlying source.

Legacy director `grant_knowledge` and `revoke_knowledge` use normal confirmation and replace the pair's previous edge. Visibility, grant/revoke node helpers, the absence helper and the ledger remain available for these scenes. Older scenes with no presence metadata do not gain historical perceptions when saved, reset or forked.
