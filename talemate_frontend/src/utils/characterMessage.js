// Parsing for the canonical character-message wire format "Name: text"
// (see CharacterMessage.with_name_prefix on the backend).

// Split a character message into its speaker name (trimmed) and raw text.
export function parseCharacterMessage(message) {
  const parts = message.split(':');
  const name = parts.shift().trim();
  return { name, text: parts.join(':') };
}
