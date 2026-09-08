# Knowledge

The World State panel offers a [knowledge hub](/talemate/user-guide/world-state/#knowledge-hub) on every character row: the newest facts the character knows and their disclosures or access rules, the Character perspectives switch, and the agent settings that shape knowledge keeping, without leaving the main view. The sections below describe the settings themselves.

## Choosing a mode

Every story runs in one of two character knowledge modes. You choose when you create the story, in the **Create New Story** dialog or in a [character card import](/talemate/user-guide/character-card-import/#character-perspectives). The choice stays open in [Scene Settings](/talemate/user-guide/world-editor/scene/settings/#character-perspectives) while the scene has no history, and locks once history exists. Both dialogs show the comparison below next to the switch.

![Create New Story dialog with the two modes side by side](/talemate/img/0.40.0/create-new-story-modes.png)

**Standard** — Characters know what they were present for and what you allow. No extra requests. You manage exceptions by hand with Allow / Block rules and the knowledge switches in Conversation settings. Good for most stories, any model, and stories without many secrets.

- Pros:
    - No extra requests
    - Works with any model
    - Nothing is locked in
    - You control exceptions directly with Allow / Block rules
- Cons:
    - A present character sees the full reader prose, private thoughts included
    - Leaks are yours to catch and fix by hand
    - The reminder and limit switches are approximate
- Pick this if: Your model is small or older, or the story has few secrets.

**Character perspectives** — After every passage the AI writes what each character actually perceived, and their replies are grounded in that. Hands-off for you: keep secrets out of the shared description, mark private entries, hand out knowledge with a disclosure when needed. One extra analytical request per passage; needs a strong, reliable model. Best for stories with secrets. **Cannot be changed once the story has history.**

- Pros:
    - Characters only know what they actually perceived
    - Secrets hold without hand-tuning
    - Hands-off once set up
    - Disclosures give exact control when needed
- Cons:
    - One extra analytical request per passage (slower, costs more)
    - Needs a strong, reliable model, or analyses fail and pause generation
    - Cannot be turned off once the story has history
    - No forget or block of already acquired knowledge
- Pick this if: Your model is current and reliable, and the story depends on who knows what.

| Pick this if | Standard | Character perspectives |
|---|---|---|
| Your model | is small or older, or you want any model to work | is current and reliable; see [Model expectations](/talemate/getting-started/model-expectations/) for what that means |
| Your story | has few secrets | depends on who knows what |
| Your workflow | you manage exceptions by hand with Allow / Block rules | hands-off once set up, with disclosures when needed |

### Effort presets

The knowledge settings of three agents decide how much work each line costs. The **Character knowledge effort** slider sets them together: drag it in the knowledge hub's **Thoroughness** section, in the Create New Story dialog next to the mode choice, or in the Conversation agent's **Character Knowledge** settings. Each stop states its extra requests and what it asks of your model; the model lines come from the [Model expectations](/talemate/getting-started/model-expectations/) page. A stop writes the same settings the individual switches do; change one switch afterwards and the slider shows **Custom** instead of overwriting your choice. A scene created without the dialog reads whatever its agents hold: with the shipped settings a Standard scene sits on Light and a Character perspectives scene on Balanced. Switching the story mode re-applies the current stop from the other table; a Standard scene on Ultra lands on Thorough, the top stop Character perspectives has.

**Standard** (five stops):

| Stop | Toggles | Extra requests | Model |
|---|---|---|---|
| **Minimal** | Character Knowledge on, Limit to character knowledge on; everything else off | None | Works with any model. |
| **Light** | Minimal + Remind about unknown facts, Topic knowledge overview, Memory Topics, Match known facts, Extract facts | None | Works with any model. |
| **Balanced** (the Create New Story default) | Light + Track learning from dialogue | One after a character message when a listener has unknown facts | Needs reliable structured output (JSON / function calls): most current hosted models and strong local models. |
| **Thorough** | Balanced + Refine memories with AI | Two | Needs a current reasoning-class model; small or older local models will produce failed analyses. |
| **Ultra** | Thorough with Unknown-fact reminders 10 and Recent facts to check 100 | Two | Current frontier / reasoning model recommended; expect frequent retries on anything less. |

**Character perspectives** (four stops; there is no Ultra, because nothing is left to raise past Thorough):

| Stop | Toggles | Extra requests | Model |
|---|---|---|---|
| **Minimal** | The analysis after each passage only; Automatic repair, Extract facts, Memory Topics and Refine memories off | The mandatory analysis | Needs reliable structured output (JSON / function calls): most current hosted models and strong local models. The analysis after each passage is mandatory in this mode, so this is the floor. |
| **Light** | Minimal + Memory Topics | The analysis | Needs reliable structured output (JSON / function calls): most current hosted models and strong local models. |
| **Balanced** (the Create New Story default) | Light + Extract facts + Automatically repair analysis | The analysis, plus a repair when a view is invalid | Needs reliable structured output (JSON / function calls): most current hosted models and strong local models. |
| **Thorough** | Balanced + Refine memories with AI | The analysis, repairs, and one before each reply with memories | Needs a current reasoning-class model; small or older local models will produce failed analyses. |

The rest of this page is the reference for both modes.

## Character perspectives (opt-in)

When creating a **New Story** or importing a character card, enable **Character perspectives** to give each character their own view of events. Turn it on to keep replies grounded in what that character has learned. The choice is **off by default**; with it off, the story uses **Standard** mode, where knowledge follows presence, ownership and sharing. The choice applies before initialization; cancelling an import or opening another one resets it.

You can also turn the mode on or off in **World Editor → Scene → Settings** while the scene has **no history and no archived history**. An intro, characters and world entries do not lock the choice. Save the scene to persist a settings change. Once history exists, the switch is disabled and the current mode is explained below it. The server also refuses changes if history appeared since the settings were displayed.

Saves, reloads and forks preserve the mode. **Scene → Shared World → New Scene** inherits it for the next episode. Stories with history cannot be converted by resaving, resetting or forking; past perceptions are not reconstructed. Turning Character perspectives off on an empty scene clears its stored perspectives and disclosures, along with the derived audience memory index. Turning it back on does not restore those records.

The reader keeps the complete prose. Characters receive stored replacement views of passages, audience summaries, disclosures and accessible memories. Missing or failed views never substitute the reader's private text. Narration and author planning can retain broader reader context; character guidance and analysis use the character evidence appropriate to their task.

### Cost and recovery

The Summarizer runs an extra analytical request after each finalized character, player or narrator passage, covering relevant audiences together. Investigations and changed tracker answers also use this analysis, including trackers that never insert a history message. Repeating an unchanged tracker answer reuses its source. Audience summaries and enabled fact extraction add work as material is summarized or rebuilt. This mode replaces **Track learning from dialogue**; it does not run both learning passes. **Refine memories with AI** remains a separate optional request before a generated character reply that has retrieved memories.

While analysis runs, dependent character generation waits. Self-citations are ignored, and correctly typed unoffered IDs are dropped with diagnostic warnings; neither discards valid character views. Missing or non-array citation fields and wrongly typed IDs invalidate the affected view and require repair. If a character view is missing or invalid, the Summarizer can try once to repair it, keeping valid views. **Automatically repair analysis** under the Summarizer’s **Character Perspectives** settings controls this extra attempt and is on by default. With automatic repair off, an unreadable citation field stops the passage and shows the generation error dialog. If analysis still fails, the generation error dialog shows the reason and offers **Retry**. Cancel or Ignore stops the dependent generation without falling back to reader text. Correct the source or client configuration and retry generation to rebuild pending views. Edits invalidate dependent views and caches; stale in-flight results cannot replace the edited source. If recording searchable facts fails or is cancelled, the information given to the character remains saved. The Knowledge tab reports that only its searchable facts could not be recorded. Retry the failed request if its dialog is still open. Otherwise, the [supported-facts rebuild API](/talemate/dev/character-perspectives/) can recover the fact record; there is no rebuild button in the Knowledge tab.

Perception uses the generating model's common-sense interpretation, not a proof of what a character understands. It must not invent an observation or event to justify knowledge. Clean inputs do not guarantee that a model will never invent an action, explanation or lucky guess.

### Author responsibilities

Keep secrets out of **scene description** and **story intention**: these remain shared authoring inputs. Set visibility on character sheets, details and world entries yourself or through the director. Do not put private instructions into a character's shared description and expect perception to remove them.

In Character perspectives mode, separate character views replace **Limit to character knowledge**, **Remind about unknown facts**, **Topic knowledge overview**, **Track learning from dialogue**, and **Match known facts**. These Standard-mode controls are hidden while Character perspectives is active. Blocking already acquired knowledge is not available in this mode. There is no forget/amnesia operation. Restricting an authored entry is not erasure of an already acquired disclosure.

## Visibility

Character descriptions, attributes, details and world entries have **Known by** settings:

- **Everyone** (default): every character can draw on the entry. Leave this selected for shared information.
- **Only [character]**: keep the entry private to its character owner. World entries have no owner, so this option reads **Nobody**.
- **Specific characters**: share the entry with its owner and the characters you choose. Select names in the **Characters** field. Explicit access rules can also give other characters access.

Set visibility in the Characters or World tab. It governs authored inputs, pins and retrieval. Generated reinforcements also need a current audience view; visibility alone cannot expose their withheld full answer. The director's `set_known_by` uses the same visibility settings and normal write confirmation.

## Explicit disclosures

In a perception scene, **Characters → Knowledge → Establish character knowledge** gives a character selected information now. Select a **Source entry** and enter **Information to disclose**. **Give selected information** copies only that text into durable knowledge; it does not unlock the containing archive or imply the character was present earlier.

**Give the whole entry** is off by default. **Give all entry content** explicitly copies all current source text, including private details. Neither choice grants access to future edits. Invalid sources and unknown characters are rejected before content is added. Earlier perspectives stay unchanged; the disclosure appears in subsequent context and survives saves, source edits and fact regeneration.

This is author establishment: no dialogue or discovery event is invented. The director's `grant_knowledge` uses the same operation, with `information` for selected text or explicit `whole_entry: true`. Removing an additional access rule does not erase information already given to the character. Revokes are unavailable in this mode, including node and API writes.

When **Extract facts** is enabled, the information also becomes searchable facts. If that step fails, the information is still saved. Follow the [cost and recovery guidance](#cost-and-recovery) to recover its facts.

## Topics and coverage

Enable [Topics in the Memory agent](/talemate/user-guide/agents/memory/settings/#topics) to group recorded facts by subject without an extra text-generation request. The Knowledge tab's **Known facts by topic** list shows **Known** facts out of **Recorded** facts in each **Topic**. In perception mode, only facts with current supporting audience evidence count. Pending or invalidated support does not count. This measures access to the index, not understanding or exhaustive world knowledge. Topics remain useful for retrieval and author inspection; characters receive no all/some/nothing topic assertions in this mode.

Each topic row expands to list that topic's facts for the character. A fact the character knows shows how they know it (**Present**, **Told in dialogue**, **Allowed by rule** or **Learned from dialogue**; in a Character perspectives story **Perceived** or **Disclosed**) and where it was recorded (the history entry, a manual entry, offscreen life, a perception or a disclosure). A recorded fact the character does not know is listed greyed, so you can see what they are missing. **Expand all** opens every row; the filter field narrows topics by name and, once a row has loaded, its facts by text, so expand a topic (or Expand all) before you search inside it. The facts load when a row opens and add no request.

![known facts by topic expanded](/talemate/img/0.40.0/world-editor-character-knowledge-topics.png)

## The director

The director can inspect full author records, visibility and character disclosures. Its **Character Knowledge** query lists disclosures, supplemental grants, restricted authored entries and recorded-fact coverage. Character-targeted guidance must respect established evidence. Normal author planning may use broader context.

## Facts in node graphs

[Knowledge nodes](/talemate/user-guide/node-editor/reference/nodes/knowledge/) provide **Facts About**, **Current State**, **Relationship Timeline**, **Entry Knowledge**, **Character Knowledge**, **Set Entry Visibility**, and **Grant Knowledge**. In perception mode, fact queries use supported character contributions and Grant Knowledge creates a disclosure. **Revoke Knowledge** rejects perception scenes before mutation. In Standard mode, these graph actions allow or block access to an entry.

## Retrieval

Perception-mode character retrieval derives queries from projected history, then ranks within eligible audience records. Similarity ranks relevance; it never grants access. Turn on [Refine memories with AI](/talemate/user-guide/agents/conversation/settings/#refine-memories-with-ai) when these available memories need a more relevant focus. See [memory settings](/talemate/user-guide/agents/memory/settings/#retrieval) for recency, diversity and local reranking.

## Standard mode

Characters' knowledge follows presence, ownership, the **Known by** settings and explicit **Allow / Block** rules. Unknown historical presence is shared. The conversation history filter replaces missed spans with a gap; layered summaries use their coarse presence. Narrator, director, summarizer and world-state author requests retain the full record.

### What the speaking character gets

Turn on **Limit to character knowledge** to omit events the character missed. If replies use information they should not know, try **Remind about unknown facts**, then adjust **Unknown-fact reminders** and **Recent facts to check**. **Topic knowledge overview** adds a short topic-level reminder. **Refine memories with AI** selects and rewrites retrieved memories; **Track learning from dialogue** records which recent facts listeners learned. See [Conversation settings](/talemate/user-guide/agents/conversation/settings/#character-knowledge) for tuning and extra-request costs. **Match known facts** can recognize retold information, but cannot override visibility or a Block rule.

### Adjust entry knowledge

In **Characters → Knowledge → Adjust entry knowledge**, select an **Entry**, choose **Allow** or **Block** under **Action**, and click **Apply**. Use Allow to add the entry to the character's knowledge; use Block to keep it out. **Note (optional)** records your reason. Select an actual autocomplete result; typing alone does not choose an entry. Block takes precedence over Allow. Remove a rule to return to the remaining knowledge rules; removing it keeps the source entry.

The director's `grant_knowledge` and `revoke_knowledge` use normal confirmation and replace the previous rule for that character and entry. The API and saved data still call Allow rules `grant` and Block rules `revoke`.
