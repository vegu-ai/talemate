# State Management

Managing transient data during a graph run is done with the **state** nodes found in
`core/state/*` and the agent-specific state nodes in `agents/*`. These nodes read from
and write to different *scopes* so that data can live for exactly as long – and be as
visible – as you need.

!!! tip "When to use state nodes"

    - Use **Local** scope to pass values between nodes or stages inside a single
      module run.
    - Use **Shared** scope to share data between modules.
    - Use **Scene loop** or **Game** scope to persist values beyond the current module
      run.
    - Use the **Agent** variants if the data belongs to a specific agent rather than
      the module itself.

---

## Core State Nodes (`state/*`)

| Node | Purpose |
|------|---------|
| `state/SetState` | Write a value into a scope |
| `state/GetState` | Read a value, with optional default |
| `state/UnsetState` | Remove a key from a scope |
| `state/HasState` | Check existence of a key, returns *exists* bool |
| `state/CounterState` | Increment (or reset) a numeric value |
| `state/Conditional*` variants | Same as above but only run when their `state` input is triggered |

All of these nodes share two mandatory properties (and matching inputs):

* **name** – the key to read/write.
* **scope** – where the key lives (see table below).

### Available Scopes

| Scope value | Container | Lifetime / Persistence | Typical use |
|-------------|-----------|------------------------|-------------|
| `local` | `state.data` | Current module run only | Passing values between nodes / stages |
| `parent` | `state.outer` | The parent module that invoked this module | Communicate results back to a caller module |
| `shared` | `state.shared` | The whole graph execution (accessible to parent and any child modules it calls) | Share values between a parent module and the sub-modules it executes |
| `scene loop` | `state.shared['scene_loop']` | While the **current** SceneLoop is running (lost if the loop restarts or errors) | Keep counters/flags for the duration of a scene loop |
| `game` | `scene.game_state` | Saved with the scene – survives reloads and is the most persistent scope | Persist values that should survive scene changes |

!!! note "Scopes are just Python dicts"
    Behind the scenes each scope is a dictionary.  Keys that you set with
    **SetState** are immediately available to any **GetState** in the same scope.

!!! info "Scene loop vs Game scope"
    *Scene loop* scope lives only as long as the active SceneLoop continues uninterrupted. If the loop is deliberately restarted or aborts due to an error, everything stored in this scope is cleared.
    *Game* scope is serialised with the scene when it is saved and restored when the scene is loaded again, making it suitable for long-term data.

!!! tip "Game state variables can control pins"
    Variables stored in the **game** scope can be used to control [context pins](/talemate/user-guide/world-editor/pins/#game-state-conditions). This allows you to automatically activate or deactivate pinned context entries based on game state values set by your node modules.

!!! info "Inspecting and editing game state variables"
    You can view and edit game state variables through the [Debug Tools](/talemate/user-guide/debug-tools/). This is useful for testing and debugging your node modules.

---

## Agent State Nodes (`agents/*`)

If the data belongs to a specific **agent** (NPC, director, etc.) you can use the
agent-aware state nodes:

* `agents/SetAgentState`
* `agents/GetAgentState`
* `agents/UnsetAgentState`
* `agents/HasAgentState`
* `agents/CounterAgentState`

They inherit the behaviour of the core state nodes but add two agent-specific
features:

1. **agent** input / property – choose the agent (instance or name).
2. **scope** can be either:
   
   - `scene` – stored in `agent.scene.agent_state`, resets when the scene changes.
   - `context` – stored in the agent's conversation context (via
     `agent.dump_context_state()`), useful for dialogue memory.

| Scope value | Container | Lifetime / Persistence |
|-------------|-----------|------------------------|
| `scene` | `agent.scene.agent_state[...]` | Saved with the scene, survives reloads |
| `context` | `agent.dump_context_state()` | Lives only for the duration of the **current agent action stack** (e.g. during a single AI task generation). Automatically cleared at the end of the originating action. |

---

## Practical Guidelines

* **Prefer local first** – Most temporary values only need to live inside the module
  run. Start with `local` and widen the scope only when necessary.

* **Reset or Unset** – Remember to clear long-lived scopes (game / scene loop) if the
  value is no longer needed; otherwise it will affect future runs.

* **Conditional variants** – Use the *Conditional* nodes when you need state changes
  to happen *only* when another branch triggers them (they expose a `state` passthrough
  similar to other conditional nodes).

* **Counters** – `CounterState` is handy for loops or retries. Use the **reset** input
  (bool) to zero the counter.

---

## Examples

### Share a value between stages

1. Earlier stage: `SetState` → `scope=local`, `name="value_to_share"`, `value=...`.
2. Later stage:  `GetState` → same scope/name, outputs the value.

### Scene-wide toggle

Use `SetState` with `scope=scene loop` in the *SceneLoop* module to keep a flag for
*just this loop*.

### Agent memory

Use `agents/SetAgentState` with `scope=context` to remember something the agent said
and `agents/GetAgentState` later to recall it during the conversation.