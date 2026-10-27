// Keys are the shipped `creator.perspective_presets` values from
// src/talemate/config/schema.py, verbatim — a preset the user renamed or added
// has no entry and simply shows no subtitle. The wording is the docs table in
// docs/user-guide/world-editor/scene/outline.md, shortened; keep the two in step.

// stands in for {player_name} in a sample line while the scene has no player
// character, as the docs table does
export const PERSPECTIVE_SAMPLE_NAME = "Annabelle";

export const PERSPECTIVE_PRESET_INFO = Object.freeze({
  "Third person limited, past tense.": {
    meaning: 'Outside narrator using "she"/"he"/"they", past tense, tied to one character.',
    sample: "{player_name} walked up to the porch. The door looked older than the rest of the house.",
  },
  "Third person limited, past tense, focused on {player_name}'s POV.": {
    meaning: "The same, with the player character named as the anchor.",
    sample: "{player_name} walked up to the porch. Something about the door felt wrong, though she couldn't say why.",
  },
  "Third person limited, present tense.": {
    meaning: 'Outside narrator using "she"/"he"/"they", present tense, tied to one character.',
    sample: "{player_name} walks up to the porch. The door looks older than the rest of the house.",
  },
  "Third person limited, present tense, focused on {player_name}'s POV.": {
    meaning: "The same, with the player character named as the anchor.",
    sample: "{player_name} walks up to the porch. The door looks wrong to her, somehow.",
  },
  "Third person omniscient, past tense.": {
    meaning: "Outside narrator who knows everything, including thoughts and off-screen events. Past tense.",
    sample: "{player_name} walked up to the porch, unaware that someone was watching her from an upstairs window.",
  },
  "Third person omniscient, present tense.": {
    meaning: "The same, in present tense.",
    sample: "{player_name} walks up to the porch. Inside, the homeowner watches her approach through the curtains.",
  },
  "First person, past tense, from {player_name}'s POV.": {
    meaning: 'The player character narrates as "I", recalling what happened.',
    sample: "I walked up to the porch. The door looked older than the rest of the house.",
  },
  "First person, present tense, from {player_name}'s POV.": {
    meaning: 'The player character narrates as "I", as it happens.',
    sample: "I walk up to the porch. The door looks older than the rest of the house.",
  },
  "Second person, present tense.": {
    meaning: 'The narrator addresses "you" — the classic interactive fiction voice.',
    sample: "You walk up to the porch. The door looks older than the rest of the house.",
  },
  "Second person, present tense. Talking to {player_name}.": {
    meaning: "The same, and the narrator knows the player character's name.",
    sample: "You walk up to the porch, {player_name}. The door looks older than the rest of the house.",
  },
});
