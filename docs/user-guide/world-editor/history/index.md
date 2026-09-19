# History

Will hold historical events for the scene.

There are three types of historical entries:

- **Archived history (static)** - These are entries are manually defined and dated before the starting point of the scene. Things that happened in the past that are **IMPORTANT** for the understanding of the world. For anything that is not **VITAL**, use world entries instead.
- **Archived history (from summary)** - These are historical entries generated from the progress in the scene. Whenever a certain token (length) threshold is reached, the [Summarizer Agent](/talemate/user-guide/agents/summarizer/) will generate a summary of the progression and add it to the history.
- **Layered history (from summary)** - As summary archives are generated, they themselves will be summarized again into compressed layers, creating a detail gradient from full detail (recent) to highly compressed (oldest). See [Layered History](layered-history.md) for details.

![History](/talemate/img/0.31.0/history.png)

### Presence

Every entry generated from a summary carries the characters that were active in the scene while its source messages were written. They show as chips next to the entry time. Layered entries show the union over the entries they summarize.

The summarizer starts a new entry whenever the active character list changes, the same way a time passage does, so a summarized entry never mixes two known sets of present characters. An entry that contains a message without presence records unknown presence as a whole. This is the record the per-character knowledge features build on.

Scenes saved before presence tracking carry no presence on their old messages, and entries built from them show no chips. Unknown presence is never guessed from who spoke: an entry without chips counts as witnessed by everyone.

### Facts

When the summarizer writes a summary entry it asks, in the same request, for the atomic facts the chapter established: one self-contained statement each, with the characters, items and places it is about, the line of the chapter it came from, the characters who learned it during the chapter, and the earlier fact it replaces, if any. This is the only place facts come from: a line that is still in the live history has no facts yet, and the AI reads the text itself until the chapter is summarized. The facts are listed under the entry with their id (`F1`, `F2`, ...), in a **Facts (N)** section that starts collapsed each time you open History; expand it to see them. A chip next to a fact names a character who learned it without being present; a repeat counter shows how often later chapters restated it; an arrow names the fact it supersedes. **Source message** opens the line the fact came from.

Each fact belongs to its line: it keeps that line's presence and scene time. Deleting the line removes the fact, unless a later line restated it (that line becomes its origin) or you edited it or gave it a Learn rule by hand (it stays, no longer tied to a line); editing the line marks it out of date until the chapter is refreshed, and editing, inserting or deleting an earlier time passage moves its time marker with the timeline. Facts are stored in the scene file and mirrored into the long term memory with that presence, so a character retrieves only the facts they know (see [Knowledge](/talemate/user-guide/world-editor/knowledge/)). A fact that repeats one already recorded is not stored again: the model names the recorded fact it repeats, and a repeat it did not name is still caught when the wording is close enough (the Summarizer's **Fact matching tolerance**). The recorded fact's repeat counter goes up and it counts as restated at that line.

To see which facts a character knows, use the [Facts tab](/talemate/user-guide/world-editor/facts/) or that character's [Knowledge tab](/talemate/user-guide/world-editor/knowledge/#topics-and-coverage).

When you select a different version of a passage, the entry that contains it shows a chip such as **Refresh facts**, **Analyze perceptions** or **Update knowledge**. Hover it to see which passage it is and why its facts are out of date; click it to run that update from here, the same as the button beside the passage. A passage that only owes learning from dialogue gets no chip here, because that changes what listeners know, not the entry's facts.

![history facts with importance and time markers](/talemate/img/0.40.0/world-editor-history-facts.png)

The importance chip shows **Routine (1)** for a smaller continuity-relevant detail, **State (2)** for a durable change, or **Milestone (3)** for firsts, revelations, deaths, and story-changing decisions. Hover it for an explanation. The extraction prompt asks the model to omit trivia and allows an empty facts list: a first hug may matter, while another routine hug does not. Facts saved before importance was added load as State (2).

Each fact also shows a relative time marker based on scene time and its latest restatement, such as **(21 Days ago)**. A fact is also listed under each later entry that restated it, with a **Restated** chip. For example, the keeper says two days ago that the lamp is out and says it again this evening: this evening's entry lists the fact with **(Recently)** and **Restated**, and the chip's tooltip tells that the fact was first recorded 2 days ago in an earlier entry. History keeps the full fact record; the Summarizer's [Fact chronology](/talemate/user-guide/agents/summarizer/settings/#fact-chronology) settings select and rank context facts without a separate AI request. [Character knowledge: flow reference](/talemate/user-guide/world-editor/knowledge-how-it-works/#standard-mode-one-line-is-said) shows how facts are recorded, restated and aged.

Double-click a fact or select its importance chip to edit its text and importance, then select **Save**. The same editor is on the topic rows of a character's [Knowledge tab](/talemate/user-guide/world-editor/knowledge/#topics-and-coverage) and in the [Facts tab](/talemate/user-guide/world-editor/facts/), which lists every fact with filters; any place changes the one record. A later restatement preserves the original fact's importance, including a manual correction. Use the :material-close: button to remove a fact. When the model's facts output could not be read, the summary is still stored and the entry shows a **facts failed** chip; **:material-format-list-checks: Regenerate facts** asks for the facts again and keeps the entry text. That request reads the chapter's lines and gives the model the stored summary only as context: it writes no new summary, and a fact the lines support counts even when the summary leaves it out or says otherwise. As known facts it offers only the facts it can place before the chapter: facts from earlier lines, disclosures given before the chapter, and static history. A fact it cannot place in the story, such as a manual fact recorded at the same scene time, is left out, and the model can link only to a fact it was offered. So an older chapter cannot replace a fact from a later one. The Summarizer's **Custom instructions** shape the summary text, so this request does not use them. Regenerating the entry itself writes a new summary and replaces its facts too. The summarizer's **Extract facts** setting turns the archive extraction off.

#### Generate missing facts

When entries have no facts yet, for example because the story was summarized while **Extract facts** was off, **:material-format-list-checks: Generate missing facts** next to the **History** heading extracts them in one go. The number on the button counts the entries that have no facts and were never tried. The entries are done oldest first, one request each, so every entry sees the facts of the entries before it. A progress bar shows how many are done. **Stop** ends the run after the entry in progress; the entries done so far keep their facts.

The button leaves alone every entry that already has facts or shows **facts failed**; use that entry's own **Regenerate facts** instead. Entries that show why extraction is unavailable are skipped too. While **Extract facts** is off, this button and each entry's **Generate facts** are unavailable, and their tooltip names the setting.

For example, the keeper's story ran for thirty chapters with **Extract facts** off. You turn it on, open History and select **Generate missing facts**. The first chapter gets its facts first, so when a later chapter says again that the lamp is out, that line is recorded as a repeat of the earlier fact, not as a new one.

#### Facts from predefined history

Static entries also offer **Generate facts**, or **Regenerate facts** after an extraction attempt or when facts already exist. This reads the saved entry text without rewriting it, adding messages, or advancing scene time. The Summarizer's **Extract facts** setting must be enabled.

In **Standard** mode, a static entry has a **Known by** field: **Everyone** (the default), **Nobody** or **Specific characters**. It decides who knows the entry and the facts recorded from it. A character who heard such a fact in a later chapter keeps it, whether you set Known by before or after that chapter. After you choose **Specific characters**, the change is saved when you pick the first name; removing the last name saves **Nobody**. A change applies to the entry's existing facts at once, with no AI request, and generation uses the same setting. The existing knowledge rules still apply on top of it. [Visibility](/talemate/user-guide/world-editor/knowledge/#visibility) has an example. Regeneration replaces the entry's facts through the same source and duplicate handling used for summarized history. Saving and reloading keeps the associations.

In **Character perspectives**, extraction uses each saved character view, preserving its audience and replacement text. An entry with missing or unfinished perspectives shows why extraction is unavailable; its full reader text is never substituted for a missing character view.

Predefined history still locks the scene's knowledge mode. You do not need to change modes or remove history to generate its facts.

History lists each summarized entry's facts under that entry. The [Facts tab](/talemate/user-guide/world-editor/facts/) lists every fact of the scene with filters.

### Managing entries

- **All entries** can be edited by double-clicking the text.
- **Static entries** can be deleted by clicking the **:material-close-box-outline: Delete** button.
- **Summarized entries** can be regenerated by clicking the **:material-refresh: Regenerate** button. This will cause the LLM to re-summarize the entry and update the text.
- **Summarized entries** can be inspected by clicking the **:material-magnify-expand: Inspect** button. This will expand the entry and show the source entries that were used to generate the summary.

### Adding static entries

Static entries can be added by clicking the **:material-plus: Add Entry** button.

!!! note "Static entries must be older than any summary entries"
    Static entries must be older than any summary entries. This is to ensure that the history is always chronological.

    Trying to add a static entry that is more recent than any summary entry will result in an error.

##### Entry Text

The text of the entry. Should be at most 1 - 2 paragraphs. Less is more. Anything that needs great detail should be a world entry instead.

You can let the AI write the entry for you with the **:material-auto-fix: Generate** button. Hold `ctrl` (or `cmd` on macOS) while clicking to provide [instructions](/talemate/user-guide/world-editor/generation-settings/#generation-instructions). For history entries your instruction is treated as the *seed* for the entry: the AI writes the entry about the event or state you describe and expands it with consistent detail, rather than ignoring it.

##### Unit

Defines the duration unit of the entry. So minutes, hours, days, weeks, months or years.

##### Amount

Defines the duration unit amount of the entry.

So if you want to define something that happened 10 months ago (from the current moment in the scene), you would set the unit to months and the amount to 10.

The scene keeps that distance. For example, you add "The war ended" 10 months ago to a new scene. After a reload, or after **Regenerate All History**, the entry still reads **10 Months ago**. When the new entry is older than every other entry, the timeline moves back to make room for it: the other entries and their facts keep their age.

![Add Static Entry](/talemate/img/0.38.0/history-add-entry.png)

## Time Passage Entries

The history view displays time passage entries with editable duration and chapter title fields. You can double-click a time passage entry to edit its duration (amount and unit) and the chapter title that names it in [Playthrough Mode](/talemate/user-guide/playthrough/#moving-around), or delete it entirely. A time passage inserted before a summarized entry can only be edited here — it sits further back than the scene view loads.

For more details on managing time passages, see the [Time Passage Management](/talemate/user-guide/time-passage/) documentation.

## Compression Statistics

The history tools menu displays layered history compression statistics for each layer. See [Layered History -- Compression Statistics](layered-history.md#compression-statistics) for details.

## Regenerate everything

It is possible to regenerate the entire history by clicking the **:material-refresh: Regenerate All History** button in the left sidebar. Static entries will remain unchanged. The regeneration also brings every passage whose selected version changed up to date, so no chapter keeps a **Refresh facts** chip; a character passage can still owe **Learn from dialogue**.

![Regenerate All History](/talemate/img/0.31.0/history-regenerate-all.png)

!!! warning "This can take a long time"

    This will go through the entire scene progress and regenerate all summarized entries.

    If you have a lot of progress, be ready to wait for a while.

## Reset Scene State

For more comprehensive reset options beyond regenerating history, see the [Reset Scene State](/talemate/user-guide/scene-state-reset/) dialog, which provides granular control over resetting history, context DB, agent states, and other scene components.
