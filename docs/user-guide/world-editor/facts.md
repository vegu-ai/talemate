# Facts

The Facts tab of the World Editor lists every fact the scene has recorded, in one place. The [History](/talemate/user-guide/world-editor/history/) tab shows facts under the history entry they came from, and a character's [Knowledge tab](/talemate/user-guide/world-editor/knowledge/#topics-and-coverage) shows what that character knows; the Facts tab answers the questions those two cannot answer without scrolling: which facts mention Nora, which are superseded, and what the latest summarized history entry added.

![facts tab](/talemate/img/0.40.0/world-editor-facts.png)

## The rows

Each row is the same record the other two tabs show. It carries the fact's id, its relative time marker, the text and the importance chip. The line under it names the source (a history entry with its id, a perception, a disclosure, a manual entry or offscreen life) and, for a fact that came from a line of the story, that line's message id, the topic when [Topics](/talemate/user-guide/agents/memory/settings/#topics) are on, the subjects, and the arrows: :material-arrow-left-bold: names the fact this one supersedes, :material-arrow-right-bold: names the fact that supersedes this one. The **N know** chip counts the characters who hold the fact; hover it for their names and how they know it (present, told in dialogue, a Learn rule or a disclosure, learned). In Character perspectives a character who holds the successor sees the older fact as retired only when their own views carry the link; an author-set link stays at the author level.

A fact is one record wherever it is shown: an edit or a removal here changes the same fact in History, in every character's Knowledge tab and in the Knowledge hub.

## Filters and sorting

The filters combine. Search matches the text, a subject or an id. Pick a character and choose whether to list the facts they **know**, the facts they **do not know**, or the facts they are **a subject** of. Narrow further by topic, by one or more importance levels, by source kind and by supersession (superseded only, or current only). **Latest** keeps the facts recorded from the newest summarized history entry, plus any fact whose line falls inside that entry; before any history entry has been summarized there are no facts to keep. The switch names the entry's age.

Sort by time (newest first by default; facts without a time sort last), by importance or by id, and flip the direction with the arrow. Fifty facts make a page; the pager sits under the list. **Reset filters** clears everything at once.

## Actions on a row

Double-click a fact, or select its importance chip, to edit its text and importance; this is the same editor as in History. The :material-dots-vertical: menu offers **Set supersedes…**, which opens a searchable list of the other facts, **Clear supersedes**, **Learn for character…** and **Never Learn for character…**, and **Inspect source** for a fact that came from a line of the story. The :material-close: button removes the fact.

A Learn after a Never Learn on the same fact lifts it, and a Never Learn added after a Learn wins over it; the character Knowledge tab follows the same order. A link that would close a loop (A supersedes B while B supersedes A) is refused and the tab says so. A fact that is no longer true is best deleted, or superseded by the fact that replaces it, as the [Knowledge](/talemate/user-guide/world-editor/knowledge/#superseded-facts) page describes.

## Several rows at once

Tick the rows, or **Select all on this page**, and the bar above the list offers **Delete** and **Learn for character**. Each runs as one request and one save, however many rows are ticked.

![facts tab selection](/talemate/img/0.40.0/world-editor-facts-selection.png)

## Character perspectives mode

In a Character perspectives story a character knows a fact through what they perceived or were given, not through an access rule, so the rows show who knows each fact but offer no **Learn** or **Never Learn**; edit, delete and the supersedes link work in both modes.

## Staying current

The tab follows the scene: an edit made in History or in a character's Knowledge tab, or a removal made in History, appears here at once, and a knowledge change (a Learn, an Unlearn, a disclosure, a fact a character learned in dialogue) refreshes the audience counts. Nothing here sends an AI request.
