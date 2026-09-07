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
| `knowledge_eligibility: perception` | Require version 1; use the integrated character-perspective pipeline. |
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

New stories default to legacy behavior. `SceneInitialization(character_knowledge=True)` opts a **new, empty history** into perception mode through `new_scene`. The public creation dialog supplies this strict boolean. It is not a runtime agent toggle and is not applied to loaded scene files. Existing scenes and character-card imports retain their saved mode; there is no historical reconstruction or conversion on reset, resave or fork. The choice persists with the scene.

`talemate.scene.format.read_scene_format(data)` is a pure metadata parser. It
returns `SavedSceneFormat` with the version actually read: 0 for an absent marker,
1 for a version-1 file. Malformed or unsupported metadata raises `SceneFormatError`.
`normalize_scene_format(data)` validates and returns a shallow copy stamped with
the current write version, preserving eligibility. Neither function reads process
configuration, modifies its input, or validates the entire scene document.

`Scene.saved_format` describes the current write representation. `Scene.serialize`
copies that metadata directly; serialization and changelog snapshots do not apply
process policy. Reconstruction validates its source before applying overrides, and overrides cannot change either metadata field.

## Public opt-in

All character-knowledge routes use the single predicate:

```python
from talemate.knowledge.mode import character_knowledge_enabled

if character_knowledge_enabled(scene):
    ...
```

It returns true for `scene.knowledge_eligibility == "perception"`. The retired `TALEMATE_DEV_CHARACTER_KNOWLEDGE` environment variable has no effect. JSON and ZIP loads support valid perception scenes directly; missing or malformed views still fail closed at their consumers.

For a deliberately authored fixture, use version 1 and `knowledge_eligibility: perception`, with valid source/view records. Do not relabel an existing playthrough to imply its missing history was reconstructed. See the [perspective record contract](character-perspectives.md) for selection, invalidation and durable disclosures, and the [user guide](/talemate/user-guide/world-editor/knowledge/#character-perspectives-opt-in) for activation and costs.
