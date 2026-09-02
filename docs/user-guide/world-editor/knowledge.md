# Knowledge

Every character draws on the same records: the scene history, the summarized history, the character sheets and the world entries. What a single character *knows* is not stored anywhere. It is worked out from those records each time the character speaks:

- A history entry, summarized or verbatim, is known to the characters that were present for it (see [History -- Presence](/talemate/user-guide/world-editor/history/#presence)). An entry with unknown presence is known to everyone.
- A character always knows their own description, attributes and details.
- Other characters' sheets and world entries are common lore, unless their visibility says otherwise.
- A fact recorded from a summary entry (see [History -- Facts](/talemate/user-guide/world-editor/history/#facts)) is known to the characters present for that entry, plus any character the summary named as having learned it, which is stored as a `told` grant.
- A **grant** adds an entry to a character's knowledge, a **revoke** takes one away. Grants and revokes are the only knowledge that is stored per character.

Only the conversation prompt is filtered this way, by the character that is speaking. The narrator, the director, the summarizer and the world state agent keep the full record.

## What the speaking character gets

When a character speaks, the scene history in their prompt drops the spans they missed and replaces each run of missed material with one line, for example `(Edwin was elsewhere for 2 hours)`. The long term memory retrieval for that prompt drops documents outside their knowledge as well, and the retrieval cache is kept per speaker.

!!! note "Layered history"
    Layered history entries summarize several base entries. Such an entry stays in a character's prompt when the character was present for *any* of its sources, so a coarse layer can still mention something the character missed. The exact filter applies to the base layer and to the memory store.

## Visibility

Each attribute, detail and description on a character sheet, and each world entry, carries a **Known by** setting:

- **Everyone** (default): every character can draw on the entry.
- **Only the owner**: only the character the entry belongs to knows it. A world entry with this setting is known to nobody until a grant names someone.
- **Specific characters**: the owner and the listed characters know it.

Set it from the entry's editor in the Characters tab (Description, Attributes, Details) or in the World tab. A grant still adds a reader to a restricted entry; a revoke removes one even from an entry that is visible to everyone. The setting applies wherever the conversation prompt shows the entry: the character sheets printed at the top of the prompt, pinned entries, and long term memory retrieval alike.

## Grants and revokes

Open a character in the Characters tab and pick the **Knowledge** tab. It lists the character's grants and revokes and lets you add one: pick the entry (a sheet entry of any character, a world entry or a summarized history entry), choose *Grant* or *Revoke*, and add an optional note. Grants and revokes made by hand carry the source `manual`; later releases add sources the story produces on its own.

## Facts in node graphs

The `knowledge/` nodes read the fact record without an LLM request: **Facts About** (facts mentioning an entity, optionally as one character knows them), **Current State** (the newest fact about an entity that no later fact supersedes), **Relationship Timeline** (facts mentioning two entities), and **Grant Knowledge** / **Revoke Knowledge** for edges written by a graph.

## Older scenes

Scenes saved before presence tracking carry no presence on their messages, so nothing is hidden from anyone in those spans. Visibility settings and grants work on such scenes as soon as you set them.
