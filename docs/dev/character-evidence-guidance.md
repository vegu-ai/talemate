# Character evidence in guidance and analysis

In opted-in perception scenes, actor guidance and conversation
analysis use the guided character's projected history, disclosures, authored entries
allowed by visibility, and last-known snapshot. These paths use `character_knowledge_enabled(scene)`; legacy
scenes retain their existing prompts and cache behavior.

The generating prompts instruct the model to preserve who claimed what, contradictory testimony,
uncertainty and established beliefs. Author goals are explicitly separate from evidence:
a director who knows a hiding place must not steer an uninformed character straight
there, or turn another character's private plan into their motive. A future disclosure
can be planned, but it has to occur before advice treats its content as learned.

Director chat, autonomous direction and all narration guidance and analysis retain
reader context. Narration keeps its subtype instructions (including visual character,
entry, exit and sensory narration) and writing-style guidance even when it has a
character subject. A separate evidence block for each character constrains suggestions
about their behavior. An unavailable character view is labeled unavailable in author
planning; it does not fall back to reader text. Actor guidance and conversation analysis block
on pending or failed projected history as other character prompts do.

Scene description and story intention remain shared author inputs: keep secrets out
of them. Authored sheets, details and world entries remain the author's visibility
responsibility. No downstream perception or rewrite request is added for advice.
The host selects evidence and validates freshness; whether prose suggestions follow
that evidence is the generating model's compliance, not a semantic guarantee enforced
by the host. Real-model checks demonstrate particular cases, not a universal boundary
against model invention.

## Retrieval, caches and insertion

Deep analysis retrieves with `rag_build(character=..., sub_instruction=...)` for
conversation analysis, so its queries and eligible candidates use that audience. Narration and other author deep
analysis retain `rag_build_for_author`. An empty new deep analysis clears prior
context in perception scenes.

Analysis and guidance caches validate the target audience, generation context,
knowledge/index revision, source identity and content, cast, visibility, scene time
and snapshot state. A changed source during generation cancels the result without
repeating its LLM requests. Direct dialogue, common character guidance and editor
insertion consult the same audience/freshness checks. The existing editor Unslop
path continues to omit character scene analysis. Director action arguments validate
evidence once before the first callback in a generated Focal response executes.
After admission, the response's callbacks may change history, time or other evidence
without cancelling their own batch, including concurrent and repeated calls. This
checks freshness during argument generation, not changes during execution of an
admitted batch; the next generated response captures a new baseline. A stale batch
cancels through both chat and autonomous direction without an internal-error result
or a follow-up LLM request. Completed action results are persisted individually.

New-mode actor context omits secret-valued absence lists and topic-awareness
assertions, even if the legacy switches are enabled. It supplies generic evidence
rules instead. The analytical absence and topic helpers remain for legacy use and
author reports.

`knowledge.advice.advice_context` assembles an audience's prompt material;
`advice_fingerprint` identifies cache freshness. Neither calls an LLM or requires a
live vector database. Authored context uses the same derived audience documents as
retrieval, including generated reinforcement entries.

Planning collects active-cast evidence using one synchronous perspective read and
one authored-document derivation. Reads are not reused across awaits. Authored text,
projected history and whole snapshot entries share the evidence allowance; oversized
entries are omitted. Each planning prompt reserves the rendered evidence block before
allocating its remaining history budget. Missing prompt material is not proof of
character ignorance.
