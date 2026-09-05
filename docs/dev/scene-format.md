# Saved scene format

Scene JSON has two independent top-level fields:

```json
{
  "format_version": 1,
  "knowledge_eligibility": "legacy"
}
```

`format_version` identifies the saved representation. It is independent of the
Talemate release, scene time, and message/changelog revision numbers. The existing
scene fields remain at the top level; runtime `Scene` is not a Pydantic model.

## Compatibility

| Input | Behavior |
| --- | --- |
| No `format_version` | Read as legacy format 0 using existing load migrations. |
| Integer `format_version: 1` | Read the current saved representation. |
| Missing `knowledge_eligibility` | Treat as `legacy`, including version-1 files. |
| `knowledge_eligibility: legacy` | Preserve existing character-knowledge behavior. |
| `knowledge_eligibility: perception` | Require version 1 and the internal development gate described below. |
| Unsupported version or malformed metadata | Reject before migrations, runtime scene assignment, ZIP extraction, or reconstructed-file writes. |

Only version 1 is explicitly supported. Zero, negative integers, strings, null,
booleans, and floating-point values are invalid version markers. Missing version
is the only spelling of legacy format 0. Unknown eligibility values also fail.
An unsupported newer scene produces an error naming its version and the supported
version; the original file is not modified. Use a Talemate release supporting that
format to open it.

New writes include version 1. Loading an old file does not rewrite it; an explicit
save upgrades only the representation. Save-as, restore saves, exports, resets,
and both shallow and reconstructed forks retain knowledge eligibility. A fork of
an unversioned historical snapshot gets version 1 with legacy eligibility, even
if the current scene has different eligibility. Existing snapshots are not rewritten.

Eligibility does **not** assert that the current code has a complete perception
pipeline, and it is not a feature toggle. Ordinary new scenes and character-card
imports remain legacy, as do older scenes after continued play or a reset. No
historical perception data is reconstructed and no extra LLM request is added by
format validation.

`talemate.scene.format.read_scene_format(data)` is a pure metadata parser. It
returns `SavedSceneFormat` with the version actually read: 0 for an absent marker,
1 for a version-1 file. Malformed or unsupported metadata raises `SceneFormatError`.
`normalize_scene_format(data)` validates and returns a shallow copy stamped with
the current write version, preserving eligibility. Neither function reads process
configuration, modifies its input, or validates the entire scene document.

`Scene.saved_format` describes the current write representation. `Scene.serialize`
copies that metadata directly; serialization and changelog snapshots do not apply
process policy. `require_character_knowledge_support(scene)` in
`talemate.knowledge.mode` applies the gate explicitly at JSON/ZIP load, scene save,
restore-save and reconstructed-file write boundaries. An unavailable perception
mode raises `TalemateError`. Reconstruction validates its source before applying
overrides, and overrides cannot change either metadata field.

## Internal development fixtures

Downstream character-knowledge code must import this **single shared predicate**:

```python
from talemate.knowledge.mode import character_knowledge_enabled

if character_knowledge_enabled(scene):
    ...
```

It returns true only when `scene.knowledge_eligibility == "perception"` **and** the
process environment contains `TALEMATE_DEV_CHARACTER_KNOWLEDGE=1`. Every other
environment value, including `true`, leaves it off. Do not read the environment
or repeat eligibility logic in downstream feature code.

For an intentionally authored development fixture, include:

```json
{
  "format_version": 1,
  "knowledge_eligibility": "perception"
}
```

Enable the environment variable before loading the fixture. In pytest, use
`monkeypatch.setenv("TALEMATE_DEV_CHARACTER_KNOWLEDGE", "1")` so it is restored
afterward. `tests/data/scene_format/perception.json` is a minimal example. Later
tickets add their own valid perspective/disclosure records to such fixtures.
Do not relabel an existing playthrough as a fixture to imply its missing history
was reconstructed.

The [character perspective record contract](character-perspectives.md) defines
optional message/summary views, independent disclosures, source content revisions,
and the shared selection and invalidation APIs for downstream development.

With the gate off, loading or saving a perception fixture fails with a clear
development-gate error. It cannot silently fall back to legacy character context.
Enabling the gate alone never changes an ordinary scene's eligibility. There is
no product setting or UI activation; issue #427 supplies the completed product
opt-in and replaces this internal gate policy.
