# Settings

## General

General summarization settings.

![Summarizer agent general settings](/talemate/img/0.40.0/summarizer-general-settings.png)

##### Client

The text-generation client to use for summarization.

##### Optimize for Prompt Caching

Places volatile context (long term memory, dynamic notes) after the scene history so that the stable part of the prompt can be cached by API backends. May confuse weaker models. `Auto` defers to the client setting.

##### Summarization

Automatically summarize scene dialogue when the number of tokens in the history exceeds a threshold. This helps keep the context history from growing too large.

A summary entry also ends early, regardless of the threshold, when a time passage occurs or when the active character list changes (a character is activated or deactivated). Every entry then records one set of present characters; see [History -- Presence](/talemate/user-guide/world-editor/history/#presence).

###### Token Threshold

The number of tokens in the history that will trigger the summarization process.

###### Summarization Method

The method used to summarize the scene dialogue. 

- `Balanced` - medium length summary
- `Short & Concise` - short summary
- `Lengthy & Detailed` - long summary
- `Factual list` - numbered list of events that transpired

###### Use preceeding summaries to strengthen context

Help the AI summarize by including the last few summaries as additional context. Some models may incorporate this context into the new summary directly, so if you find yourself with a bunch of similar history entries, try setting this to 0.

###### Custom instructions

Custom instructions for the summarization agent. These instructions are included in the summarization prompt to guide how summaries are generated. Use this to customize the summarization style, focus areas, or format for your specific needs.

Writing style instructions are also included during summarization to maintain consistency with your scene's chosen writing style.

###### Extract facts

Save individual facts alongside summaries for character knowledge. **Leave on to build the fact record**; this summary step needs no extra request, so every effort stop above Off keeps it on. On by default. With this off, regenerating an entry leaves its recorded facts as they are, and nothing re-extracts facts after an edit. An edit of a character line inside a summarized chapter keeps the line's facts, bound to the edited text, when the Conversation agent's **Track learning from dialogue** runs for the line. With that off too, or for a narrator line, the edit removes the stale chapter summary and its facts. The latest chapter is summarized again by the next archive step, without facts; an older chapter is not rebuilt until you regenerate the history. See [History — Facts](/talemate/user-guide/world-editor/history/#facts).

Chapter summaries are the only source of facts. Each fact names the line of the chapter it came from and keeps that line's presence and scene time; it is removed with the line, marked out of date when the line is edited until the chapter is refreshed, and moves with the timeline when an earlier time passage changes. A fact the model cannot tie to a line is not stored.

[Character knowledge: flow reference](/talemate/user-guide/world-editor/knowledge-how-it-works/#standard-mode-one-line-is-said) shows who learns a chapter's facts. Extraction asks for facts whose omission could make a later scene go wrong, allowing **0–12 facts per chapter**. A first hug can be a relationship milestone; a routine greeting hug is not a new fact. Each fact receives an **importance** of Routine (1), State (2), or Milestone (3) in the same response. These are model judgments that can be corrected in History; facts saved before importance was added default to State (2).

###### Fact matching tolerance

Treat sufficiently similar facts as repeats instead of saving them again (default 0.15). **Raise to merge more similar facts; lower to keep more distinctions.** The extraction itself names the recorded fact a statement repeats; this tolerance catches the repeats it did not name. A repeat increases the stored fact's repeat counter.

This is the maximum distance allowed between normalized fact embeddings. Zero is the strictest value, not an off switch. In Standard mode, the Memory agent's [Match known facts](/talemate/user-guide/agents/memory/settings/#match-known-facts) also uses this tolerance when checking retold information. In Perspectives mode it also merges similar facts extracted by different audiences from the same moment.

## Fact chronology

Fact chronology selects context facts by importance and age without a separate AI request. The **Character knowledge effort** slider leaves these settings untouched; you can also override them for one scene. [Facts age](/talemate/user-guide/world-editor/knowledge-how-it-works/#facts-age) explains it in plain words.

![Summarizer agent fact chronology settings](/talemate/img/0.40.0/summarizer-fact-chronology-settings.png)

| Setting | Default | Meaning |
| --- | --- | --- |
| Milestone half-life (days) | 90 | Time for a Milestone (3) score to halve |
| State half-life (days) | 14 | Time for a State (2) score to halve |
| Routine half-life (days) | 2 | Time for a Routine (1) score to halve |
| Recent facts window (days) | 3 | Newer facts remain eligible in full |
| Older facts score floor | 0.5 | Older facts need a score above this, or must mention a present character; 0 disables the age-based cut |
| Show formerly clause | On | Include one short previous-fact clause on its successor when both are prompt candidates |

The score is `importance / (1 + age_days / half_life)`. Age uses scene time and the latest of the fact's original or restatement time. A restated fact becomes fresh again. For example, a first hug yesterday scores about 2.97, ahead of a month-old milestone at 2.25. Existing fact and token limits still apply.

Superseded facts leave prompt lists when their successor is accessible to that viewer. **Show formerly clause** appends the immediate predecessor's text to its successor, limited to 240 characters and without another time marker. It never expands an entire chain or changes recorded access. History and Knowledge inspection keep the records. See [Superseded facts](/talemate/user-guide/world-editor/knowledge/#superseded-facts) for the per-character example. The setting adds no AI requests and also refreshes cached Standard analysis when changed.

With the defaults, facts that do not concern a present character are excluded from context at **3 days for Routine**, **42 days for State**, and **450 days for Milestone**, measured since their latest restatement. The present-character exception matches recorded **subjects**, including character aliases. Only facts with no subjects fall back to a name match in their text. For example, with Will present, “The ship will dock tomorrow” is not kept merely for the word “will” when its subject is the ship. Names containing punctuation, such as `C++`, also match. Routine facts remain eligible throughout the recent window even after their score reaches the floor. At the window boundary or later, the score must be strictly above the floor. Set **Older facts score floor** to **0** to keep older facts eligible; ranking and existing prompt limits still apply.

Context fact lists use this selection and ranking. Unknown-fact reminders first take the newest records by original creation order according to **Recent facts to check**, then apply chronology within that pool. Retrieved memories retain their query-relevance, recency-weight and cross-encoder order; chronology only selects eligible facts and adds time markers there. The previous-facts lists supplied to fact extraction are ranked without the age-based cut, then bounded by their existing limit, so extraction can still recognize an older fact or its replacement.

Every rendered fact includes a relative time such as **(1 Day ago)** or **(21 Days ago)**. Undated facts show **(Time unknown)** and remain eligible; future timestamps count as fresh. History and the full Knowledge topic list retain older facts for inspection even when prompts omit them. Character perspectives applies the same rules to each character's supported evidence; private restatements cannot make another character's facts fresher. Aging does not erase knowledge. Cached Standard conversation analysis is refreshed when its inputs change, as described under **Cache analysis** below.

## Character Perspectives

The Character Perspectives section is visible with any scene or with no scene loaded.
Its settings only affect scenes using character perspectives.
Automatic repair can add one Summarizer request when a view is missing or invalid.
The same toggle and cost note are available in the World State knowledge hub.
[Character knowledge: flow reference](/talemate/user-guide/world-editor/knowledge-how-it-works/#character-perspectives-mode-one-line-is-said) shows the analysis, repair and Retry flow.

![Summarizer agent character perspectives settings](/talemate/img/0.40.0/summarizer-character-perspectives-settings.png)

##### Automatically repair analysis

When a character’s view is missing or invalid, make one extra request to repair it before showing the generation error dialog. Valid views are kept. On by default; turn off to use manual retries only. This setting applies to stories using [Character perspectives](/talemate/user-guide/world-editor/knowledge/). Self-citations and correctly typed unoffered IDs do not trigger repair. Missing or non-array citation fields and wrongly typed IDs require repair.
With automatic repair off, an unreadable citation field stops the passage and shows the generation error dialog.

## Layered History

Settings for the layered history summarization.

Talemate `0.28.0` introduces a new feature called layered history summarization. This feature allows the AI to summarize the scene dialogue in layers, with each layer providing a different level of detail.

Not only does this allow to keep more context in the history, albeit with earlier layers containing less detail, but it also allows us to do history investgations to extract relevant information from the history during conversation and narration prompts.

Right now this is considered an experimental feature, and whether or not its feasible in the long term will depend on how well it works in practice.

![Summarizer agent layered history settings](/talemate/img/0.40.0/summarizer-layered-history-settings.png)

##### Enable Layered history

Allows you to enable or disable the layered history summarization.

!!! note "Enabling this on big scenes"
    If you enable this on a big established scene, the next time the summarization agent runs, it will take a while to process the entire history and generate the layers.

##### Token Threshold

The number of tokens in the layer that will trigger the summarization process to the next layer.

##### Maximum number of layers

The maximum number of layers that can be created. Raising this limit past 3 is likely to have dimishing returns. We have observed that usually by layer 3 you are down to single sentences for individual events, making it difficult to summarize further in a meaningful way.

##### Maximum tokens to process

Smaller LLMs may struggle with accurately summarizing long texts. This setting will split the text into chunks and summarize each chunk separately, then stitch them together in the next layer. If you're using a strong LLM (70B+), you can try setting this to be the same as the threshold.

Setting this higher than the token threshold does nothing.

##### Chunk size

During the summarization itself, the text will be furhter split into chunks where each chunk is summarized separately. This setting controls the size of those chunks. This is a character length setting, **NOT** token length.

##### Enable analysation

Analyses the chunks and their relationship to each other before summarization. This can greatly improve the quality of the summarization, but will also result in a bigger size requirement of the output.

##### Maximum response length

The maximum length of the response that the summarizer agent will generate.

!!! info "Analyzation requires a bigger length"
    If you enable analyzation, you should set this to be high enough so the response has room for both the analysis and the summary of all the chunks.

## Long term memory

--8<-- "docs/snippets/tips.md:agent_long_term_memory_settings"

## Scene Analysis

![Summarizer agent scene analysis settings](/talemate/img/0.40.0/summarizer-scene-analysis-settings.png)

When enabled scene analysis will be performed during conversation and narration tasks. This analysis will be used to provide additional context to other agents, which should hopefully improve the quality of the generated content.

In Character Perspectives mode, scene analysis waits for knowledge updates already running before it takes its inputs: snapshots, summaries, perceptions, facts, character-detail **Refresh State** and world-entry **Reset State Reinforcement** operations, and memory indexing. Refreshes started by applying a template, or by creating or saving a state with an immediate update, are not covered by this wait. The status line shows **Waiting for knowledge updates before scene analysis**; Scene Direction and the director chat use the same wait before they run the chosen actions. Cancel releases the wait even if background work is still finishing. Waiting starts no update or AI request. Standard mode does not use this wait.

An update that starts after the inputs were taken can still make them outdated and stop generation. A warning explains that stop, or reports unavailable character knowledge, so you can retry. User cancellation, including loading another scene, does not produce this system-abort warning.

##### Length of analysis

The maximum number of tokens for the response. (e.g., how long should the analysis be).

##### Conversation

Enable scene analysis for conversation tasks.

In Standard mode, the Conversation agent's **Character Knowledge** master switch also gives the analysis **Known facts** and **Unknown recent facts** for the character. The analysis uses these lists to judge awareness and avoid suggesting actions based on information the character missed. This applies even when **Limit to character knowledge** or **Remind about unknown facts** is off.

Known facts follow importance and recency scores and the Fact chronology cut; facts too large for the remaining budget are skipped. Unknown facts use **Unknown-fact reminders** and **Recent facts to check** from Conversation settings. Each list uses up to one sixth of the client's context budget, plus headings; their actual size is reserved from scene history. The blocks are omitted when neither list has facts that fit. Analysis always keeps its instruction to use established story facts without assumptions. This adds prompt content without another AI request.

##### Narration

Enable scene analysis for narration tasks.

##### Deep analysis

Performs targeted memory retrieval based on the initial analysis, surfacing additional relevant context for the other agents.

##### Cache analysis

Reuse the analysis when you regenerate the most recent output, including directed regeneration or choosing a different version of that reply.

A completed analysis is also kept if a later step stops the turn. With caching enabled, retrying reuses it as long as its inputs are still current. If Deep analysis was interrupted, retry repeats its unfinished memory retrieval using the saved investigation, without requesting the initial analysis again. This retrieval can make its usual memory requests; an interrupted attempt does not count as completed context.

!!! info
    This cache is anchored to the last message in the scene (excluding the current message). Editing that message will invalidate the cache.

In Character perspectives mode, a new player line, an earlier passage edit, a disclosure, a fact change, or a change to the character's supplied evidence, scene description, intention or analysis context budget refreshes the analysis; browsing the reply and routine memory indexing do not.

In Standard mode with Character Knowledge enabled, the cache fingerprint includes the target character, the knowledge record (including Learn, Never Learn and Unlearn rules, and the Known by of static history entries), the complete recorded facts, the analysis context budget, Conversation's **Recent facts to check** and **Unknown-fact reminders**, the Summarizer's **Fact matching tolerance**, and whether memory is ready. It also includes all five resolved **Fact chronology** settings (including scene overrides), the current scene time, and the sorted names of active characters. Changing any of these inputs invalidates the cached conversation analysis so the next analysis request uses current fact selection and time markers. Checking the fingerprint itself makes no AI request.

## Scene History

Controls how scene history is split between actual dialogue and summarized content when generating context for AI prompts. The same controls apply to the reader-facing Scene view and to each character's stored views in Character perspectives mode. These settings can also be adjusted and previewed through the [Scene Context tab](/talemate/user-guide/prompts/context-history-review/) in the Prompt Manager.

##### Max. Budget

Cap the context budget for scene history in tokens. Set to 0 to use the full available budget dictated by prompt type and client context limits.

- **Range**: 0 -- 262144
- **Default**: 8192
- **Step**: 512

##### Best Fit Mode

Automatically distribute budget across layers to cover the full timeline with a detail gradient -- compressed at the start, detailed at the end. When enabled, the dialogue ratio and summary detail ratio sliders are replaced by automatic optimization.

- **Default**: On

When best fit mode is enabled, two additional controls become available:

##### Min. Dialogue Messages

Minimum number of recent eligible messages guaranteed in best-fit mode, regardless of budget. In Character perspectives mode, these are stored character views: the scan crosses summary boundaries when needed and skips passages the character did not witness or cannot read. The guaranteed window may exceed the token budget. Set to 0 to disable.

- **Range**: 0 -- 15
- **Default**: 5

##### Max. Dialogue Messages

Maximum number of raw messages selected in best-fit mode, including messages exposed by later detail expansion. This is a cap, not a requested amount of detail; summaries still cover older history when possible. An effective maximum lower than Min. Dialogue is raised to the minimum.

- **Range**: 10 -- 500
- **Default**: 250

When best fit mode is disabled, you have direct control over the budget distribution:

##### Dialogue Ratio

Percentage of context budget allocated to actual scene dialogue when Best Fit Mode is off. Higher values preserve more recent conversation at the expense of summarized history. Character perspectives applies the same allocation to stored message views.

- **Range**: 10% -- 90%
- **Default**: 50%

##### Summary Detail Ratio

Percentage of remaining budget allocated to each successive summary layer when Best Fit Mode is off. Higher values give more budget to recent, detailed summaries, including stored audience summaries in Character perspectives mode.

- **Range**: 10% -- 90%
- **Default**: 50%

##### Enforce Summary Boundary

When enabled, dialogue will not expand into content that has already been summarized, producing the most compact context rendering at the cost of detail. When disabled, older messages may reappear in full as dialogue expands into previously summarized content.

- **Default**: Off

--8<-- "docs/snippets/tips.md:character_evidence_guidance"
