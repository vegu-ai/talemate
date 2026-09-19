# Generation action identity

The prompt log reads an action from `ActiveAgentContext.action`. An agent method
decorated with `set_processing` establishes that context and scopes
`config.agent_actions.overrides["<agent>.<action>"]` to its request. On return,
the caller's context and overrides are restored.

Distinct request steps use these action keys:

| Agent | Action |
| --- | --- |
| conversation | `memory_pass` |
| editor | `revision_rewrite`, `revision_unslop` |
| director | `plan_expand_beats`, `plan_critique_expanded_blocks`, `chat_generate_title` |
| help | `chat_generate_title` |
| visual | `apply_ai_finalizer` |
| world_state | `generate_reinforcement` |

The shared title and director request utilities retain their calling agent's
context. Perception analysis uses `summarizer.analyze_perceptions`.

Foreground processing remains a count of active calls. Each invocation registers
its action until it exits, including exceptional and cancelled exits. Status
shows the most recently started active foreground action, or an active background
action when no foreground action remains. Background work does not increment the
foreground counter. Request metadata always uses its own context, independently
of which concurrent action the status display currently shows.
