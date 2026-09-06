# Knowledge

The presence-based behavior below applies to legacy scenes. Internally enabled perception scenes use stored audience views and [explicit disclosures](#explicit-disclosures-development-mode); the complete opt-in mode is still under development.

Every character draws on the same records: the scene history, the summarized history, the character sheets and the world entries. What a single character *knows* is not stored anywhere. It is worked out from those records each time the character speaks:

- A history entry, summarized or verbatim, is known to the characters that were present for it (see [History -- Presence](/talemate/user-guide/world-editor/history/#presence)). An entry with unknown presence is known to everyone.
- A character always knows their own description, attributes and details.
- Other characters' sheets and world entries are common lore, unless their visibility says otherwise.
- A fact recorded from a summary entry (see [History -- Facts](/talemate/user-guide/world-editor/history/#facts)) is known to the characters present for that entry, plus any character the summary named as having learned it, which is stored as a `told` grant.
- A **grant** adds an entry to a character's knowledge, a **revoke** takes one away. Grants and revokes are the only knowledge that is stored per character.

Only the conversation prompt is filtered this way, by the character that is speaking. The narrator, the director, the summarizer and the world state agent keep the full record.

## What the speaking character gets

When a character speaks, the scene history in their prompt drops the spans they missed and replaces each run of missed material with one line, for example `(Edwin was elsewhere for 2 hours)`. Director instructions, state reinforcements and context investigations are kept whatever the presence says: they are instructions to the actor, not story the character lived through. The long term memory retrieval for that prompt drops documents outside their knowledge as well, and the retrieval cache is kept per speaker.

### What the speaking character does not know

The prompt also gets a short section, *What X does not know*, built from the most recent facts: the facts outside the character's knowledge, minus any that sit next to a fact they do know (someone told them later, and the retold fact is a near-duplicate of the original), the most restated first, capped at five lines. The section is only rendered when it has content, so a character who knows everything recent gets no section. Facts come from summarized entries, and the span a returning character missed is summarized once the first message after their return is archived, so the section catches up on that character's second turn after the return. The switch and the cap live in the conversation agent's [Character Knowledge](/talemate/user-guide/agents/conversation/settings/#character-knowledge) settings, together with the perspective filter itself.

!!! note "Layered history"
    Layered history entries summarize several base entries. Such an entry stays in a character's prompt when the character was present for *any* of its sources, so a coarse layer can still mention something the character missed. The exact filter applies to the base layer and to the memory store.

## Visibility

Each attribute, detail and description on a character sheet, and each world entry, carries a **Known by** setting:

- **Everyone** (default): every character can draw on the entry.
- **Only the owner**: only the character the entry belongs to knows it. A world entry with this setting is known to nobody until a grant names someone.
- **Specific characters**: the owner and the listed characters know it.

Set it from the entry's editor in the Characters tab (Description, Attributes, Details) or in the World tab. A grant still adds a reader to a restricted entry; a revoke removes one even from an entry that is visible to everyone. The setting applies wherever the conversation prompt shows the entry: the character sheets printed at the top of the prompt, pinned entries, and long term memory retrieval alike.

## Grants and revokes

Open a character in the Characters tab and pick the **Knowledge** tab. It lists the character's grants and revokes and lets you add one: pick the entry (a sheet entry of any character, a world entry, or a static or summarized history entry), choose *Grant* or *Revoke*, and add an optional note. A static history entry is common lore, so a revoke is the only way to hide one from a character. Grants and revokes made by hand carry the source `manual`, and the ones the [director](#the-director) writes carry `director`. The story produces two more: `told`, when a summary names a character who learned a fact while absent, and `inferred`, from the conversation agent's [learned-this-turn ledger](/talemate/user-guide/agents/conversation/settings/#learned-this-turn-ledger).

The **Entry** field is searchable: type part of an entry's name or fact text, then select
a result. Typing alone does not select an entry, so **Add** stays disabled until you pick
one. Removing a grant or revoke keeps the underlying entry available to select again.

## The director

The [director chat](/talemate/user-guide/agents/director/chat/) reads and changes the same records, without an extra request beyond the call it already makes.

Whenever the director looks at an entry, the entry carries a **Known by** line: the visibility setting, or the present characters of a summarized history entry, followed by the grants and revokes on it, for example `Known by: only Bob (owner); grants: Alice (director, "she read the ledger")`. The line appears in the context the director's update and query tools are given and under the value of a directly retrieved entry. In legacy scenes, the **Character Knowledge** query action answers "what does Alice know" with the character's grants and revokes, the restricted entries they can see, and the coverage table and awareness line the Knowledge tab shows. In perception scenes it also lists [explicit disclosures](#explicit-disclosures-development-mode) under their own heading; entry grants/revokes, restricted entries and coverage remain separate.

The **Character Knowledge** entry in the Update Context group of the director's actions gives it three operations, each confirmed like any other write action when confirmation is on:

- `set_known_by` sets the Known by of a sheet entry or a world entry (everyone, only the owner, or a list of characters). It refuses history entries.
- `grant_knowledge` grants a character an entry (a sheet entry, a world entry or a history entry), with an optional note.
- `revoke_knowledge` revokes one, with an optional note.

An entry can be named by its hashed Context ID or by its readable name, as everywhere else. Edges the director writes carry the source `director`, and one edge per character and entry is kept: a revoke after a grant replaces the grant, and a later grant replaces the revoke.

## Topics and coverage

The memory agent clusters the stored facts into [topics](/talemate/user-guide/agents/memory/settings/#topics) by embedding, without a request. A character's **Knowledge** tab shows a coverage table: per topic, how many of its facts the character knows, largest topics first, with the awareness line the conversation prompt carries above it. Coverage follows the same rules as everything else on this page: presence, grants and revokes decide which facts count as known.

## Facts in node graphs

The `knowledge/` nodes read the fact record without an LLM request: **Facts About** (facts mentioning an entity, optionally as one character knows them), **Current State** (the newest fact about an entity that no later fact supersedes), **Relationship Timeline** (facts mentioning two entities), and **Grant Knowledge** / **Revoke Knowledge** for edges written by a graph, which take the entry as an id or as a Context ID item, with a note, a source and a switch to keep one edge per character and entry. **Entry Knowledge** gives an entry's Known by line and edges, **Set Entry Visibility** sets the Known by of a sheet entry or world entry, and **Character Knowledge** renders the report the director's query uses. In perception scenes **Grant Knowledge** uses `information` for the selected text and `whole_entry` for explicit copying of all content, returning a `disclosure`; see [explicit disclosures](#explicit-disclosures-development-mode). See the [node reference](/talemate/user-guide/node-editor/reference/nodes/knowledge/).

## Retrieval

Memory retrieval for a speaking character is filtered by their knowledge, and the [Memory agent's Retrieval settings](/talemate/user-guide/agents/memory/settings/#retrieval) shape what the filter sees: newer results rank higher (recency weight), near-identical results are skipped (diversity threshold), a character named in the recent lines but not in the scene has their description fetched from the memory store (entity lookup), and a result outside the character's knowledge still passes when a fact they do know is a near-duplicate of it (similarity knowledge gate). An optional local cross-encoder reranks the merged results. None of these adds a request.

Two opt-ins on the conversation agent add one request each: the [AI memory pass](/talemate/user-guide/agents/conversation/settings/#ai-memory-pass), which rewrites the retrieved memories as what the character knows and orders them for the next line, and the [learned-this-turn ledger](/talemate/user-guide/agents/conversation/settings/#learned-this-turn-ledger). The narrator's [Offscreen Life](/talemate/user-guide/agents/narrator/settings/#offscreen-life) writes what a returning character did while away and stores it as a fact only they know (source `offscreen`).

## Older scenes

Scenes saved before presence tracking carry no presence on their messages, so nothing is hidden from anyone in those spans. Visibility settings and grants work on such scenes as soon as you set them.


## Explicit disclosures (development mode)

In an internally enabled perception scene, the character’s **Knowledge** tab offers **Establish character knowledge**. Select an existing **Source entry** and enter the **Information to disclose**. **Give selected information** copies only that text into this character’s durable knowledge now. For example, disclosing “The ledger is under the bed” does not also disclose a betrayal plan in the same archive.

**Give the whole entry** is off by default. Turning it on and choosing **Give all entry content** copies *all* current text of the selected entry, including private details. Neither operation grants ongoing access to future edits of that entry. Both preserve the copied information when the source or its extracted facts are regenerated. Invalid or removed sources and unknown characters are rejected without adding content.

This is explicit author establishment: no dialogue or event is invented to justify learning. Earlier character perspectives stay unchanged. Disclosures appear in later actor history and audience summaries in acquisition order, and survive saving and reloading. Ordinary learning from generated narrative continues through the perception lifecycle.

The director’s `grant_knowledge` uses the same operation and usual write confirmation. `information` contains the selected text; `whole_entry` defaults to false and must be true only for an explicit request to give all entry content. Its confirmation states the choice. Existing legacy scenes keep their entry-grant instructions, note examples and confirmation. Existing grants/revokes remain visible and removable in perception scenes because they still affect supplemental routes; removing one does not remove a disclosure.

When fact extraction is enabled, disclosure facts use the existing summarizer extraction request and contribution index. The disclosure is retained if extraction fails; the error dialog can retry extraction. If retry is cancelled, the Knowledge tab shows a warning. A supported-facts rebuild from saved sources can recover its facts later (the developer API is `SummarizeAgent.rebuild_supported_facts`; see the [developer guide](/talemate/dev/character-perspectives/)).

These controls do not enable the full perception mode. Unconverted supplemental prompt and retrieval routes remain later integration work; this page does not claim they are protected by disclosure handling. Visibility of authored sheets and world entries remains the author’s responsibility.
