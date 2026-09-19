# Knowledge

The World State panel offers a [knowledge hub](/talemate/user-guide/world-state/#knowledge-hub) on every character row: the character’s known facts ranked by importance and recency and their disclosures or access rules, the Character perspectives switch, and the agent settings that shape knowledge keeping, without leaving the main view. The sections below describe the settings themselves. [Character knowledge: flow reference](/talemate/user-guide/world-editor/knowledge-how-it-works/) shows the flow behind them, with diagrams.

## Choosing a mode

Every story runs in one of two character knowledge modes. You choose when you create the story, in the **Create New Story** dialog or in a [character card import](/talemate/user-guide/character-card-import/#character-perspectives). The choice stays open in [Scene Settings](/talemate/user-guide/world-editor/scene/settings/#character-perspectives) while the scene has no history, and locks once history exists. Both dialogs show the comparison below next to the switch.

![Create New Story dialog with the two modes side by side](/talemate/img/0.40.0/create-new-story-modes.png)

**Standard** — Characters know what they were present for and what you let them learn. No extra requests. You manage exceptions by hand with Learn / Never Learn rules and the knowledge switches in Conversation settings. Good for most stories, any model, a small cast, and stories without many secrets.

- Pros:
    - No extra requests
    - Works with any model
    - Nothing is locked in
    - You control exceptions directly with Learn / Never Learn rules
- Cons:
    - A present character sees the full reader prose, private thoughts included
    - Leaks are yours to catch and fix by hand
    - The reminder and limit switches are approximate
- Pick this if: Your model is small or older, the story has few secrets, or the scene is mostly you and one character.

**Character perspectives** — After every passage the AI writes what each character actually perceived, and their replies are grounded in that. Hands-off for you: keep secrets out of the shared description, mark private entries, hand out knowledge with a disclosure when needed. One extra analytical request per passage; needs a strong, reliable model. Best for stories with secrets and several active characters who know different things. **Cannot be changed once the story has history.**

- Pros:
    - Characters only know what they actually perceived
    - Secrets hold without hand-tuning
    - Hands-off once set up
    - Disclosures give exact control when needed
- Cons:
    - One extra analytical request per passage (slower, costs more)
    - Needs a strong, reliable model, or analyses fail and pause generation
    - Cannot be turned off once the story has history
    - No Unlearn or Never Learn for knowledge a character already has
- Pick this if: Your model is current and reliable, the story depends on who knows what, and several characters are active who know different things.

| Pick this if | Standard | Character perspectives |
|---|---|---|
| Your model | is small or older, or you want any model to work | is current and reliable; see [Model expectations](/talemate/getting-started/model-expectations/) for what that means |
| Your story | has few secrets | depends on who knows what |
| Your workflow | you manage exceptions by hand with Learn / Never Learn rules | hands-off once set up, with disclosures when needed |
| Your cast | is mostly you and one character | has several active characters who know different things |

### Effort presets

The knowledge settings of three agents decide how much work each line costs. The **Character knowledge effort** slider sets them together: drag it in the knowledge hub's **Thoroughness** section, in the Create New Story or character-card import dialog next to the mode choice, in the Conversation agent's **Character Knowledge** settings, or in the [scene header](/talemate/user-guide/scene-header/#knowledge-effort) once you add its **Knowledge effort** item. The explanation separates **Requests**, conditional **Retries**, and potential **Benefit**, with a brief model caveat. It follows effective settings and scene overrides, including Custom combinations. A stop writes the same settings the individual switches do; change one afterwards and the slider shows the stop the settings now match, or **Custom** when they match none, instead of overwriting your choice. A scene created without the dialog reads whatever its agents hold: with the shipped settings a Standard scene sits on Light and a Character perspectives scene on Balanced. Switching the story mode re-applies the current stop from the other table; a Standard scene on Ultra lands on Thorough, the top stop Character perspectives has.

Selections in **Create New Story** and **Character Card Import** are saved as [scene overrides](/talemate/user-guide/agents/scene-overrides/), including values already equal to your global defaults. Both dialogs start at **Balanced**. The settings apply before the new story starts its knowledge work; global agent settings remain unchanged. The card import slider controls ongoing knowledge effort independently of the import's **AI Generation** options. Save a new blank story normally to keep its scene file and settings link. In the knowledge hub, **Use global settings** clears the selected group or the whole hub's overrides and restores inheritance.

**Standard** (six stops):

| Stop | Toggles | Extra requests | Model |
|---|---|---|---|
| **Off** | Character Knowledge off, Memory Topics off, Match known facts off; Extract facts stays as it is | None | Works with any model. |
| **Minimal** | Character Knowledge on, Limit to character knowledge on, Extract facts on; everything else off | None | Works with any model. |
| **Light** | Minimal + Remind about unknown facts, Topic knowledge overview, Memory Topics, Match known facts | None | Works with any model. |
| **Balanced** (the Create New Story default) | Light + Track learning from dialogue | One after a character message when a listener has unknown facts | Needs reliable structured output (JSON / function calls): most current hosted models and strong local models. |
| **Thorough** | Balanced + Refine memories with AI | One after applicable dialogue; one before a generated reply with uncached memories | Needs a current reasoning-class model; small or older local models will produce failed analyses. |
| **Ultra** | Thorough with Unknown-fact reminders 10 and Recent facts to check 100 | One after applicable dialogue; one before a generated reply with uncached memories | Current frontier / reasoning model recommended; expect frequent retries on anything less. |

**Off** is how Talemate worked before character knowledge: every character sees the full scene history, and nothing costs a request. It is on the Standard track only. Character perspectives builds each character's views whatever the Character Knowledge switch holds, so an Off stop there would still leave the analysis after each passage and the character filtering running, and it could not deliver the pre-feature behaviour; carrying Off across to Character perspectives lands on Minimal instead.

**Character perspectives** (four stops; there is no Ultra, because nothing is left to raise past Thorough):

| Stop | Toggles | Extra requests | Model |
|---|---|---|---|
| **Minimal** | The analysis after each passage and Extract facts; Automatic repair, Memory Topics and Refine memories off | The mandatory analysis | Needs reliable structured output (JSON / function calls): most current hosted models and strong local models. The analysis after each passage is mandatory in this mode, so this is the floor. |
| **Light** | Minimal + Memory Topics | The analysis | Needs reliable structured output (JSON / function calls): most current hosted models and strong local models. |
| **Balanced** (the Create New Story default) | Light + Automatically repair analysis | The analysis, plus a repair when a view is invalid | Needs reliable structured output (JSON / function calls): most current hosted models and strong local models. |
| **Thorough** | Balanced + Refine memories with AI | The analysis, repairs, one before each reply with memories | Needs a current reasoning-class model; small or older local models will produce failed analyses. |

The counts describe normal requests, excluding provider/network retries. Dialogue
learning adds one request when listeners have unknown recent facts; it grants
recorded facts and records none. Memory refinement skips empty retrievals
and reuses cached results. Character return transitions add no request at any effort setting.

Character perspectives requires one analysis per eligible passage with an audience,
covering the requested characters together. Missing or invalid views can add one
automatic repair request when enabled. It also builds summaries for distinct
character views; their request count depends on the views and summary chunks.
Extracting facts alongside a summary adds no separate request. These costs have
different triggers and are not a single per-dialogue total.

### What an existing scene loads with

A scene saved before this release loads in **Standard** mode. Its effort is not stored with the scene: the slider reads the global Conversation, Summarizer and Memory settings, unless the scene carries an agent override for one of them.

Changes made through the knowledge hub are **scene overrides** stored in the project's agent-settings file. Global agent settings are left untouched. **Overrides are project-scoped and shared across every save in the project, including stock scenes, Save As copies and restore points.** A stock scene's read-only protection applies to its scene save, not to the project's overrides: hub edits apply directly without a Save Scene dialog. Saves auto-link the project's default settings file on load, so loading the stock scene again picks up those changes too. A scene explicitly linked to a different settings file, or opted out of overrides, follows that choice; [Per-Scene Agent Overrides](/talemate/user-guide/agents/scene-overrides/) explains these options. The agent settings dialog (the Agents page) remains the place to change the globals. The hub marks each value that comes from a scene override and offers **Use global settings** on a group header and above the effort slider; a reset removes only the knowledge settings the hub owns — including ones the current mode hides — and leaves every unrelated override in place. The effort chip above the slider says **Global settings** when none of the current mode's effort settings is overridden and **Scene override** when any is, and its tooltip tells a scene that supplies every effort setting from one that mixes scene overrides with globals. When a story has no save file, changing a hub setting opens **Save Scene** and continues the pending change after saving succeeds. Cancelling or a failed save preserves the change and entered name; see [first-save continuation, retry and discard](/talemate/user-guide/agents/scene-overrides/#saving-a-knowledge-hub-change-for-the-first-time).

To get the behaviour Talemate had before character knowledge, drag the slider to **Off**, its first stop. The slider is in the knowledge hub's **Thoroughness** section, in the **Create New Story** dialog and in the Conversation agent's **Character Knowledge** settings. Off writes the Character Knowledge switch itself and the two switches outside it, Memory Topics and Match known facts; Extract facts costs no request and stays as it is. The switches under that master keep the values they held, because a master that is off makes every one of them inert; turning the master back on by hand brings those values back, and the slider reads the stop they match, or **Custom** when they match none.

The rest of this page is the reference for both modes.

## Character perspectives (opt-in)

When creating a **New Story** or importing a character card, enable **Character perspectives** to give each character their own view of events. Turn it on to keep replies grounded in what that character has learned. The choice is **off by default**; with it off, the story uses **Standard** mode, where knowledge follows presence, ownership and sharing. The choice applies before initialization; cancelling an import or opening another one resets it.

You can also turn the mode on or off in **World Editor → Scene → Settings** while the scene has **no history and no archived history**. An intro, characters and world entries do not lock the choice. Save the scene to persist a settings change. Once history exists, the switch is disabled and the current mode is explained below it. The server also refuses changes if history appeared since the settings were displayed.

Saves, reloads and forks preserve the mode. **Scene → Shared World → New Scene** inherits it for the next episode. Stories with history cannot be converted by resaving, resetting or forking; past perceptions are not reconstructed. Turning Character perspectives off on an empty scene clears its stored perspectives and disclosures, along with the derived audience memory index. Turning it back on does not restore those records.

Predefined static history also keeps the mode locked. Use [History → Generate facts](history/index.md#facts-from-predefined-history) to extract facts from those entries in their current mode, without adding story progress.

The reader keeps the complete prose. Characters receive stored replacement views of passages, audience summaries, disclosures and accessible memories. Missing or failed views never substitute the reader's private text. Narration and author planning can retain broader reader context; character guidance and analysis use the character evidence appropriate to their task.

### Cost and recovery

The Summarizer runs an extra analytical request after each finalized character, player or narrator passage, covering relevant audiences together. Investigations and changed tracker answers also use this analysis, including trackers that never insert a history message. Repeating an unchanged tracker answer reuses its source. Audience summaries and enabled fact extraction add work as material is summarized or rebuilt. This mode replaces **Track learning from dialogue**; it does not run both learning passes. **Refine memories with AI** remains a separate optional request before a generated character reply that has retrieved memories.

While analysis runs, dependent character generation waits. Self-citations are ignored, and correctly typed unoffered IDs are dropped with diagnostic warnings; neither discards valid character views. Missing or non-array citation fields and wrongly typed IDs invalidate the affected view and require repair. If a character view is missing or invalid, the Summarizer can try once to repair it, keeping valid views. **Automatically repair analysis** under the Summarizer’s **Character Perspectives** settings controls this extra attempt and is on by default. With automatic repair off, an unreadable citation field stops the passage and shows the generation error dialog. If analysis still fails, the generation error dialog shows the reason and offers **Retry**. Cancel or Ignore stops the dependent generation without falling back to reader text. Correct the source or client configuration and retry generation to rebuild pending views. Edits invalidate dependent views and caches; stale in-flight results cannot replace the edited source. If recording searchable facts fails or is cancelled, the information given to the character remains saved. The Knowledge tab reports that only its searchable facts could not be recorded. Retry the failed request if its dialog is still open. Otherwise, the [supported-facts rebuild API](/talemate/dev/character-perspectives/) can recover the fact record; there is no rebuild button in the Knowledge tab.

Perception uses the generating model's common-sense interpretation, not a proof of what a character understands. It must not invent an observation or event to justify knowledge. Clean inputs do not guarantee that a model will never invent an action, explanation or lucky guess.

### Author responsibilities

Keep secrets out of **scene description**, **story intention** and **current scene intention**. The scene description remains a shared authoring input in dialogue and guidance; story and current scene intention reach perception analysis as well. Set visibility on character sheets, details and world entries yourself or through the director. Do not put private instructions into a character's shared description and expect perception to remove them.

In Character perspectives mode, separate character views replace **Limit to character knowledge**, **Remind about unknown facts**, **Topic knowledge overview**, **Track learning from dialogue**, and **Match known facts**. These Standard-mode controls are hidden while Character perspectives is active. **Never Learn** and **Unlearn** are not available in this mode, and there is no other forget operation. Restricting an authored entry is not erasure of an already acquired disclosure.

## Scene introductions

The introduction belongs to the characters active when it is established. A character activated later does not receive it in their filtered history, analysis or memories. The original audience stays attached to the introduction through saves and character renames; replacing the introduction records the currently active characters as its new audience.

In Character perspectives mode, that audience shares the same opening text. Talemate does not generate separate intro perspectives or make an extra AI request. The reader/player display retains the introduction. Shared author-facing history inserts a separate introduction only when no summaries or dialogue expanded from them are selected.

For a scene saved before introduction audiences existed, loading derives the audience once from the first narrative message's recorded presence. If that message has no presence record, or there is no narrative history, it uses the restored active roster. The result is saved with the scene, including an explicitly empty audience. This is a load convention, not a reconstruction of who actually witnessed an older opening.

If the first summary's audience includes someone outside the opening audience, the introduction stays separate from that summary and its extracted facts. Characters can still receive their own dialogue and summaries without acquiring the opening.

## Character activation and return

Scene history marks each time an existing character is called into the scene or taken out of it, for example from the World panel or the World Editor. Calling them in adds a chip labelled **[Name] activated** in the character's color; taking them out adds a **[Name] deactivated** chip. A character that is created in the scene, or that is already present when a scene loads, gets no **[Name] activated** chip. One exception: when the Director creates a character who has not arrived yet, a **[Name] deactivated** chip appears at creation. The chips appear in every scene, with or without Character Knowledge. They have no delete button; removing the character from the scene removes their chips.

Click an activated chip to see a short summary: *First time in the scene*, or *Back after 2 days away*, and who was present at entry. Click the chip again to close it. A deactivated chip has no details.

When transitions are on, the activated chip also gives the character a **re-entry bridge** in their own context: they are back after being away, with the duration when scene time records one. In Standard mode this needs **Limit to character knowledge**; Character perspectives always uses it. With transitions off, the chips are markers only and add nothing to any prompt.

The absence runs from the character's deactivated chip to their activated chip. A time passage placed between the two counts as time away; one placed before the deactivated chip does not. With no recorded time passage or no departure time, the bridge says “after being away” without assigning a duration. A first arrival does not invent an absence.

While transitions are on, the opened chip offers an **Arrival Note (Optional)** field. Use it to say how the character arrives, for example “Edwin comes through the garden gate carrying a sealed letter.” The note becomes part of the bridge. It is saved shortly after you leave the field, and the field keeps its unsaved color until the save is done. Writing a note starts no request.

The bridge does not replay the last exchange before departure or give the returning character private events they missed. In Standard mode the story they missed shows once, as a line such as *(Edwin was away for a while.)*. The bridge stays in the character's chronological context, and is protected through their first completed reply even after a long absence.

Returning only records that the character was away and how much scene time passed. What they did while away can come out naturally as the story continues.

Each return remains distinct through saves and reloads. Edits to time passages update the duration; deleting a time-passage message updates the duration too. Rewinding or resetting history removes later chips. Loading an already active character or replacing their actor adds no chip.

## Fact relevance

The age-based relevance exception for a present character uses the fact's subjects and character aliases. A fact with no subjects falls back to a name match in its text; an unrelated subject prevents incidental words such as “will” from keeping a fact just because Will is present. This affects prompt relevance, not knowledge access.

## Superseded facts

When a newer fact supersedes an older one, prompt lists omit the older fact. The rule uses the character's knowledge: someone who knows where Mara used to keep the sextant but has not learned that she moved it still receives the old fact. History and Knowledge inspection retain both records and their supersedes links; access is unchanged.

**Show formerly clause**, under Summarizer → **Fact chronology**, is on by default. If both records are in the list's candidates, the successor can include a short clause: `Mara moved the sextant to her bag. (formerly: Mara keeps the sextant in the drawer.)` Only the immediate predecessor appears, capped at 240 characters, with no separate time marker. For A → B → C, C is rendered with B as formerly; A is omitted. Turning the setting off removes the clause while keeping the older fact out of prompt lists. This is a rendering rule and adds no AI requests.

## Visibility

Character descriptions, attributes, details and world entries have **Known by** settings:

- **Everyone** (default): every character can draw on the entry. Leave this selected for shared information.
- **Only [character]**: keep the entry private to its character owner. World entries have no owner, so this option reads **Nobody**.
- **Specific characters**: share the entry with its owner and the characters you choose. Select names in the **Characters** field. A Learn rule can also give other characters access.

Set visibility in the Characters or World tab. It governs authored inputs, pins and retrieval. Learn and Never Learn rules apply in the order you add them: a **Learn** added after a **Never Learn** on the same entry or fact lifts the Never Learn, and a **Never Learn** added after a **Learn** wins over it. The character's Knowledge tab and the [Facts tab](/talemate/user-guide/world-editor/facts/) follow the same rule. Generated reinforcements also need a current audience view; visibility alone cannot expose their withheld full answer. The director can set **Known by** for you as well, through its usual write confirmation.

In a Standard story a static history entry, the backstory you add in the [History](/talemate/user-guide/world-editor/history/) tab, has the same **Known by** field. It decides who knows the entry and every fact recorded from it. Say the entry reads "Mara's brother drowned off Vester Point" and only Mara should know it: choose **Specific characters** and Mara. From then on only Mara draws on the entry and its facts. The change reaches the facts the entry already has at once, without an AI request, and **Generate facts** uses the same setting. A Character perspectives story does not offer the field.

## Explicit disclosures

In a perception scene, **Characters → Knowledge → Establish character knowledge** gives a character selected information now. Select a **Source entry** and enter **Information to disclose**. **Give selected information** copies only that text into durable knowledge; it does not unlock the containing archive or imply the character was present earlier.

**Give the whole entry** is off by default. **Give all entry content** explicitly copies all current source text, including private details. Neither choice grants access to future edits. Invalid sources and unknown characters are rejected before content is added. Earlier perspectives stay unchanged; the disclosure appears in subsequent context and survives saves, source edits and fact regeneration.

This is author establishment: no dialogue or discovery event is invented. The director can give a disclosure the same way, with selected information or the whole entry. Removing an additional access rule does not erase information already given to the character. Never Learn rules (**Revoke Knowledge** in node graphs) are unavailable in this mode, including node and API writes.

When **Extract facts** is enabled, the information also becomes searchable facts. If that step fails, the information is still saved. Follow the [cost and recovery guidance](#cost-and-recovery) to recover its facts.

## Topics and coverage

Enable [Topics in the Memory agent](/talemate/user-guide/agents/memory/settings/#topics) to group recorded facts by subject without an extra text-generation request. The Knowledge tab's **Known facts by topic** list shows **Known** facts out of **Recorded** facts in each **Topic**. In perception mode, only facts with current supporting audience evidence count. Pending or invalidated support does not count. This measures access to the index, not understanding or exhaustive world knowledge. Topics remain useful for retrieval and author inspection; characters receive no all/some/nothing topic assertions in this mode.

Each topic row expands to list that topic's facts for the character. A fact the character knows shows how they know it (**Present**, **Told in dialogue**, **Learn rule** or **Learned from dialogue**; in a Character perspectives story **Perceived** or **Disclosed**) and where it was recorded (the history entry, a manual entry, a perception or a disclosure). A recorded fact the character does not know is listed greyed with the reason (**Not present**, **Unlearned** or **Never Learn rule** in a Standard story), so you can see what they are missing. **Expand all** opens every row; the filter field narrows topics by name and, once a row has loaded, its facts by text, so expand a topic (or Expand all) before you search inside it. The facts load when a row opens and add no request. Double-click a fact in a topic row, or select its importance chip, to edit its text and importance. In a Standard story a fact the character knows offers **Unlearn**, and a fact they do not know offers **Learn**; see [Unlearn a fact](#unlearn-a-fact). A topic row never deletes the fact itself: delete a fact in the History tab or the [Facts tab](/talemate/user-guide/world-editor/facts/). A fact is one record wherever it is shown: an edit in a topic row, in the History tab, in the Facts tab or through the Knowledge hub changes the same fact for every character. Until you edit it, a fact that Character perspectives merged from two characters' views keeps each character's own wording in their Knowledge tab; your edit replaces both.

Facts show relative time markers based on their latest known restatement. The hub applies the Summarizer's [Fact chronology](/talemate/user-guide/agents/summarizer/settings/#fact-chronology) order and cut; expanded topic rows keep the full record for inspection. The score combines importance and age, with recent facts retained and older facts kept when salient or about a present character. This adds no AI request and leaves character access and the effort slider unchanged.

![known facts by topic expanded](/talemate/img/0.40.0/world-editor-character-knowledge-topics.png)

## The director

The director can inspect full author records, visibility and character disclosures. Its **Character Knowledge** query lists disclosures, Learn, Never Learn and Unlearn rules, restricted authored entries and recorded-fact coverage. Character-targeted guidance must respect established evidence. Normal author planning may use broader context.

## Facts in node graphs

[Knowledge nodes](/talemate/user-guide/node-editor/reference/nodes/knowledge/) provide **Facts About**, **Current State**, **Relationship Timeline**, **Entry Knowledge**, **Character Knowledge**, **Set Entry Visibility**, and **Grant Knowledge**. In perception mode, fact queries use supported character contributions and Grant Knowledge creates a disclosure. **Revoke Knowledge** rejects perception scenes before mutation. In Standard mode, **Grant Knowledge** adds a Learn rule and **Revoke Knowledge** adds a Never Learn rule for an entry.

## Retrieval

Perception-mode character retrieval derives queries from projected history, then ranks within eligible audience records. Similarity ranks relevance; it never grants access. Turn on [Refine memories with AI](/talemate/user-guide/agents/conversation/settings/#refine-memories-with-ai) when these available memories need a more relevant focus. See [memory settings](/talemate/user-guide/agents/memory/settings/#retrieval) for recency, diversity and local reranking.

## Standard mode

Characters' knowledge follows presence, ownership, the **Known by** settings, explicit **Learn / Never Learn** rules and **Unlearn**. Unknown historical presence is shared. The conversation history filter replaces missed spans with a gap; layered summaries use their coarse presence. Narrator, director, summarizer and world-state author requests retain the full record.

When you select a different revision of a message, Standard mode temporarily withholds facts and inferred grants that came from the replaced text, including affected chapter summaries. **Refresh facts** re-runs enabled fact extraction for the chapter summaries that contain the passage and, for character dialogue, enabled learning from dialogue; a passage outside every chapter has no facts to refresh. A passage that owes only learning from dialogue, such as a character line that no chapter contains yet, shows **Learn from dialogue** instead. It uses the presence and preceding history recorded at that point rather than today's active cast. Sending the next line runs the same refresh first. In the World Editor's History tab, a history entry that contains a passage whose facts are out of date shows a chip with the same label; click it to run the refresh from there. Regenerating the whole history re-extracts every chapter's facts from the selected versions, so afterwards only learning from dialogue can still be owed, and the button reads **Learn from dialogue**. Selecting the earlier version again after that asks for **Refresh facts**, because the facts now come from the other version. Authored facts, Learn rules, other restatements and unrelated evidence are preserved; with both features disabled, cleanup waits until you send your next line and makes no model request. Browsing leaves the scene unsaved; the selection persists with the next scene save.

### What the speaking character gets

Turn on **Limit to character knowledge** to omit events the character missed. If replies use information they should not know, try **Remind about unknown facts**, then adjust **Unknown-fact reminders** and **Recent facts to check**. **Topic knowledge overview** adds a short topic-level reminder. **Refine memories with AI** selects and rewrites retrieved memories; **Track learning from dialogue** records which recent facts listeners learned. See [Conversation settings](/talemate/user-guide/agents/conversation/settings/#character-knowledge) for tuning and extra-request costs. **Match known facts** can recognize retold information, but cannot override visibility, a Never Learn rule or an Unlearn.

### Adjust entry knowledge

In **Characters → Knowledge → Adjust entry knowledge**, select an **Entry**, choose **Learn** or **Never Learn** under **Action**, and click **Apply**. Use Learn to add the entry to the character's knowledge; use Never Learn to keep it out, even when the character is present when the story repeats it. **Note (optional)** records your reason. Select an actual autocomplete result; typing alone does not choose an entry. The rules apply in the order you add them: a Never Learn added after a Learn wins over it, and a Learn added after a Never Learn lifts the Never Learn. Remove a rule to return to the remaining knowledge rules; removing it keeps the source entry.

The director can add a Learn or Never Learn rule the same way, through its usual confirmation; its actions call them grant and revoke. Rules accumulate rather than replace one another: a Learn added after a Never Learn removes that Never Learn, while a Never Learn added after a Learn is listed beside it and wins; remove that Never Learn and the Learn stands again.

### Unlearn a fact

A fact row under **Characters → Knowledge → Known facts by topic** offers **Unlearn** when the character knows the fact and **Learn** when they do not. Unlearn takes the fact out of what this character knows; the fact stays for everyone else. Say Edwin was present when Mara hid the sextant, but he should find out later in the story: Unlearn the fact on Edwin's tab. Edwin stops knowing it at once, and the rule list shows an **Unlearn** rule for it.

Unlike Never Learn, an Unlearn lets the character learn the fact again. A later line that teaches it lifts the rule: Mara telling Edwin in a new line while **Track learning from dialogue** is on, or a new passage that repeats the fact while Edwin is present. The rule stays in the list, marked **lifted by a later line**, for as long as that line is in the story. If you delete or regenerate the line, or pick a version of it that no longer teaches the fact, the Unlearn applies again and Edwin stops knowing the fact. Regenerating an older chapter or refreshing an older passage does not lift the rule, because nothing new happened in the story. When you regenerate the chapter that recorded the fact, regenerate its facts or regenerate the whole history, the rule moves to the fact that the regeneration records for the same statement from the same passage. Every Learn and Never Learn rule on the fact moves the same way, and so does what a character learned about it from dialogue. When you refresh the passage instead, a Learn or Never Learn by hand keeps the fact in place, no longer tied to the line, and an Unlearn waits and moves as above. If the regeneration does not record the statement again, the rule waits outside the list until a later regeneration records it, and it goes when its passage is deleted. A **Learn** by hand replaces the Unlearn for good, and so does a Never Learn. Remove the Unlearn rule to undo it: what the story taught Edwin, such as a fact Mara told him, applies again. Unlearn applies to facts only.
