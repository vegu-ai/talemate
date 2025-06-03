# Template Functions

List of functions available in prompt templates.

## Function Index

| Function | Category |
|----------|----------|
| [`set_prepared_response`](#set_prepared_response) | Response Control |
| [`set_data_response`](#set_data_response) | Response Control |
| [`disable_dedupe`](#disable_dedupe) | Response Control |
| [`query_scene`](#query_scene) | Scene Queries |
| [`query_memory`](#query_memory) | Memory Queries |
| [`query_text`](#query_text) | Text Analysis |
| [`query_text_eval`](#query_text_eval) | Text Analysis |
| [`instruct_text`](#instruct_text) | Text Analysis |
| [`agent_action`](#agent_action) | Agent Operations |
| [`agent_config`](#agent_config) | Agent Operations |
| [`time_diff`](#time_diff) | Time Operations |
| [`text_to_chunks`](#text_to_chunks) | Text Processing |
| [`to_int`](#to_int) | Type Conversion |
| [`to_str`](#to_str) | Type Conversion |
| [`len`](#len) | Utility Functions |
| [`max`](#max) | Utility Functions |
| [`min`](#min) | Utility Functions |
| [`join`](#join) | String Operations |
| [`data_format_type`](#data_format_type) | Data Formatting |
| [`count_tokens`](#count_tokens) | Token Operations |
| [`llm_can_be_coerced`](#llm_can_be_coerced) | LLM Operations |
| [`config`](#config) | Configuration |

## Filter Index

| Filter | Category |
|--------|----------|
| [`condensed`](#condensed) | Text Formatting |

## Functions

### set_prepared_response

Can be used to scaffold the beginning of the agent response while making sure that the string provided will still be part of the response.

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `response` | str | The string to prepend to the agent response. |
    | `prepend` | str | Additional string to prepend to the agent response. (will be lost from the response) |

```jinja2
<|SECTION:TASK|>
Count to 10.
<|CLOSE_SECTION|>
{{ set_prepared_response("1 2 3 4") }}
```

Will result in the following response:

```
1 2 3 4 5 6 7 8 9 10 followed by whatever else the agent is going to hallucinate today.
```

---

```jinja2
<|SECTION:TASK|>
Count to 10.
<|CLOSE_SECTION|>
{{ set_prepared_response("2 3 4", prepend="1 ") }}
```

Will result in the following response:

```
2 3 4 5 6 7 8 9 10 followed by whatever else the agent is going to hallucinate today.
```

### set_data_response

Scaffolds a data structure (JSON or YAML) for the agent to complete. The function partially serializes the provided object, allowing the agent to continue and complete the structure. Format is automatically determined by the client's preferred data format.

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `initial_object` | dict | The data structure to partially serialize |
    | `instruction` | str | Optional instruction/schema comment (default: "") |
    | `cutoff` | int | Number of lines to trim from the end of serialization (default: 3) |

!!! example "Example: JSON Format"

    ```jinja2
    <|SECTION:TASK|>
    Generate character attributes for a fantasy RPG character.

    I want the following attributes:

    - name
    - class
    - level
    - attributes
      - strength
      - dexterity
      - intelligence
      - wisdom
      - constitution
      - charisma

    <|CLOSE_SECTION|>
    {{ set_data_response({
        "name": ""
    }, instruction="Generate a complete character sheet") }}
    ```

    Will scaffold the response as:

    ```json
    // Generate a complete character sheet
    { "name":
    ```

    And the agent might complete it as:

    ```json
    // Generate a complete character sheet
    { "name": "Thorin Ironforge", "class": "Warrior", "level": 5, "attributes": { "strength": 18, "dexterity": 12, "intelligence": 10, "wisdom": 14, "constitution": 16, "charisma": 8 } }
    ```

!!! note "Format Selection"
    The data format (JSON or YAML) is automatically determined by:
    
    1. The client's `data_format` attribute if available
    2. Otherwise defaults to the format specified in `data_format_type` (default: "json")

!!! tip "Minimal Scaffolding"
    Provide minimal structure to give the agent maximum flexibility. The function automatically trims the serialization to create an incomplete structure that the agent must complete:

    ```jinja2
    {{ set_data_response({
        "items": []
    }) }}
    ```

    Results in (JSON):
    ```json
    { "items": [
    ```

    This allows the agent to generate the entire array contents and any additional properties.

---

### disable_dedupe

Disables deduplication for the prompt text. By default, Talemate removes duplicate lines from prompts to save tokens. This function prevents that behavior for the current prompt.

!!! payload "Arguments"

    This function takes no arguments.

!!! example "Example"

    ```jinja2
    {{ disable_dedupe() }}
    <|SECTION:EXAMPLES|>
    The cat sat on the mat.
    The cat sat on the mat.
    The cat sat on the mat.
    <|CLOSE_SECTION|>
    ```

    Without `disable_dedupe()`, duplicate lines would be removed. With it, all three identical lines are preserved.

---

### query_scene

Queries the narrator agent to answer questions about the current scene. This function is useful for extracting specific information or generating context-aware content based on the scene state.

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `query` | str | The question to ask about the scene. Supports template variables. |
    | `at_the_end` | bool | Whether to append context at the end (default: True) |
    | `as_narrative` | bool | Whether to format as narrative text (default: False) |
    | `as_question_answer` | bool | Whether to format as Q&A pair (default: True) |

!!! example "Example: Basic Query"

    ```jinja2
    {{ query_scene("What is the current weather?") }}
    ```

    Returns:
    ```
    Question: What is the current weather?
    Answer: The sky is overcast with dark storm clouds gathering on the horizon. A cold wind blows through the trees.
    ```

!!! example "Example: With Template Variables"

    ```jinja2
    {{ query_scene("What is {character.name} currently doing?") }}
    ```

    Returns:
    ```
    Question: What is Alice currently doing?
    Answer: Alice is sitting by the fireplace, reading an old leather-bound book.
    ```

!!! example "Example: Narrative Format"

    ```jinja2
    {{ query_scene("Describe the atmosphere in the room", as_narrative=true, as_question_answer=false) }}
    ```

    Returns just the answer without Q&A formatting:
    ```
    The room is dimly lit by flickering candles, casting dancing shadows on the walls. A sense of unease permeates the air.
    ```

---

### query_memory

Queries the memory agent to retrieve stored information about characters, events, or world state. Useful for maintaining consistency and recalling past events.

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `query` | str | The question to ask. Supports template variables. |
    | `as_question_answer` | bool | Whether to format as Q&A pair (default: True) |
    | `**kwargs` | dict | Additional arguments passed to the memory agent |

!!! example "Example: Basic Memory Query"

    ```jinja2
    {{ query_memory("What do we know about the ancient artifact?") }}
    ```

    Returns:
    ```
    Question: What do we know about the ancient artifact?
    Answer: The artifact is a golden amulet discovered in the ruins. It bears strange inscriptions and glows faintly in moonlight.
    ```

!!! example "Example: Multi-Query with Iteration"

    ```jinja2
    {{ query_memory("What is Alice's favorite color?\nWhat is Bob's occupation?\nWhere did they first meet?", iterate=true) }}
    ```

    Returns concatenated answers for multiple queries.

---

### query_text

Analyzes provided text and answers questions about it. Uses the world state agent's text analysis capabilities.

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `query` | str | The question to ask about the text |
    | `text` | str or list | The text to analyze (list will be joined with newlines) |
    | `as_question_answer` | bool | Whether to format as Q&A pair (default: True) |
    | `short` | bool | Whether to limit response to ~10 tokens (default: False) |

!!! example "Example: Analyzing Text"

    ```jinja2
    {% set description = "The old mansion stood atop the hill, its broken windows staring like hollow eyes. Vines crept up the crumbling walls." %}
    {{ query_text("What condition is the building in?", description) }}
    ```

    Returns:
    ```
    Question: What condition is the building in?
    Answer: The building is in a state of severe disrepair and abandonment, with broken windows and crumbling walls overtaken by vegetation.
    ```

!!! example "Example: Short Answer"

    ```jinja2
    {{ query_text("Is this a modern building?", description, short=true, as_question_answer=false) }}
    ```

    Returns:
    ```
    No, it's old and abandoned.
    ```

---

### query_text_eval

Evaluates a yes/no question about provided text. Returns a boolean value based on the text analysis.

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `query` | str | The yes/no question to evaluate |
    | `text` | str | The text to analyze |

!!! return "Returns"

    `bool` - True if the answer starts with "yes", False otherwise

!!! example "Example: Boolean Evaluation"

    ```jinja2
    {% set scene_text = "The room was pitch black. Sarah couldn't see anything." %}
    {% if query_text_eval("Is the room dark?", scene_text) %}
    Sarah fumbles for a light switch.
    {% else %}
    Sarah surveys the well-lit room.
    {% endif %}
    ```

!!! example "Example: Character State Check"

    ```jinja2
    {% if query_text_eval("Is the character injured?", history[-1].text) %}
    {{ character.name }} winces in pain with each movement.
    {% endif %}
    ```

---

### instruct_text

Analyzes text and follows specific instructions about it using the world state agent. This is useful for extracting, transforming, or generating content based on provided text.

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `instruction` | str | The instruction to follow. Supports template variables. |
    | `text` | str or list | The text to analyze (list will be joined with newlines) |

!!! example "Example: Summarizing Text"

    ```jinja2
    {% set long_description = "The ancient castle stood majestically on the cliff, its weathered stone walls telling stories of centuries past. Moss covered the northern tower, while the eastern wing showed signs of recent repairs. The courtyard bustled with activity as merchants set up their stalls for the morning market." %}
    {{ instruct_text("Summarize this in one sentence", long_description) }}
    ```

    Returns:
    ```
    An ancient castle on a cliff hosts a busy morning market in its courtyard.
    ```

!!! example "Example: Extracting Information"

    ```jinja2
    {% set character_intro = "My name is Elena Blackwood. I'm 28 years old and work as a detective in the city. I have dark hair and green eyes." %}
    {{ instruct_text("Extract only the physical description", character_intro) }}
    ```

    Returns:
    ```
    Dark hair and green eyes.
    ```

!!! example "Example: Transforming Style"

    ```jinja2
    {{ instruct_text("Rewrite this in a more ominous tone", "The sun was setting over the quiet village.") }}
    ```

    Returns:
    ```
    Shadows lengthened as the dying sun bled crimson over the unnaturally silent village.
    ```

---

### agent_action

Executes a specific action on any agent and returns the result. This provides direct access to agent capabilities from within templates.

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `agent_name` | str | The name of the agent (e.g., "narrator", "world_state") |
    | `_action_name` | str | The method name to call on the agent |
    | `**kwargs` | dict | Additional keyword arguments passed to the action |

!!! example "Example: Calling Narrator Action"

    ```jinja2
    {{ agent_action("narrator", "narrate_query", query="What time of day is it?") }}
    ```

!!! example "Example: World State Analysis"

    ```jinja2
    {{ agent_action("world_state", "analyze_text", text="The room was cold and damp.", instruction="What can we infer about this location?") }}
    ```

!!! warning "Advanced Feature"
    This function provides low-level access to agent methods. Use with caution and ensure you understand the agent's API before calling its methods directly.

---

### agent_config

Retrieves configuration values from agent actions. Useful for accessing agent-specific settings within templates.

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `config_path` | str | Path to config in format: "agent_name.action_name.config_name" |

!!! return "Returns"

    The configuration value, or an empty string if the path is invalid.

!!! example "Example: Getting Configuration Value"

    ```jinja2
    {% set response_length = agent_config("conversation.generation_override.length") %}
    {% if response_length > 500 %}
    <|SECTION:INSTRUCTIONS|>
    Generate a detailed response.
    <|CLOSE_SECTION|>
    {% else %}
    <|SECTION:INSTRUCTIONS|>
    Keep your response concise.
    <|CLOSE_SECTION|>
    {% endif %}
    ```

!!! example "Example: Checking Feature Status"

    ```jinja2
    {% if agent_config("narrator.narrate.allow_dialogue") == "true" %}
    You may include character dialogue in your narration.
    {% endif %}
    ```

!!! note "Configuration Path"
    The path follows the pattern `agent_name.action_name.config_name`. If any part of the path is invalid, an empty string is returned.

---

### time_diff

Converts an ISO8601 timestamp to a human-readable time difference relative to the current scene time.

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `iso8601_time` | str | ISO8601 formatted timestamp |

!!! return "Returns"

    A human-readable string describing the time difference (e.g., "2 hours ago", "in 3 days")

!!! example "Example: Time Since Event"

    ```jinja2
    {% if last_seen_timestamp %}
    {{ character.name }} was last seen {{ time_diff(last_seen_timestamp) }}.
    {% endif %}
    ```

    Might produce:
    ```
    Alice was last seen 3 hours ago.
    ```

    **Note:** `last_seen_timestamp` is not a real variable, it's just an example of how to use the function. Talemate uses iso8601 timestamps to timestamp messages and keep track of scene time.

    Historic events entered into long term memory will also have explicit timestamps.

---

### text_to_chunks

Splits text into chunks of approximately equal size, useful for processing long texts in manageable pieces.

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `text` | str | The text to split into chunks |
    | `chunk_size` | int | Target size for each chunk in characters (default: 512) |

!!! return "Returns"

    A list of text chunks, each approximately `chunk_size` characters

!!! example "Example: Processing Long Text"

    ```jinja2
    {% set long_text = scene.get_history_text() %}
    {% set chunks = text_to_chunks(long_text, 1000) %}
    
    <|SECTION:SCENE HISTORY|>
    {% for chunk in chunks[:3] %}
    Part {{ loop.index }}:
    {{ chunk }}
    
    {% endfor %}
    {% if chunks|length > 3 %}
    ... ({{ chunks|length - 3 }} more parts)
    {% endif %}
    <|CLOSE_SECTION|>
    ```

!!! example "Example: Iterating Through Chunks"

    ```jinja2
    {% for chunk in text_to_chunks(document, 256) %}
    {{ query_text("Summarize the main point", chunk) }}
    {% endfor %}
    ```

!!! note "Chunk Boundaries"
    The function respects line breaks and attempts to avoid splitting in the middle of sentences when possible.

---

### to_int

Converts a value to an integer. Useful for type conversion in template logic.

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `x` | any | The value to convert to integer |

!!! return "Returns"

    The integer representation of the value

!!! example "Example: String to Integer"

    ```jinja2
    {% set level_string = "5" %}
    {% set level = to_int(level_string) %}
    {% if level > 3 %}
    This is a high-level character.
    {% endif %}
    ```

!!! example "Example: Numeric Comparisons"

    ```jinja2
    {% set health_percent = to_int(character.health) / to_int(character.max_health) * 100 %}
    Character health: {{ to_int(health_percent) }}%
    ```

---

### to_str

Converts a value to a string. Useful for string operations on numeric or other types.

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `x` | any | The value to convert to string |

!!! return "Returns"

    The string representation of the value

!!! example "Example: Number to String"

    ```jinja2
    {% set count = 42 %}
    {% set message = "There are " + to_str(count) + " items" %}
    {{ message }}
    ```

!!! example "Example: Building Dynamic Text"

    ```jinja2
    {% set level = 10 %}
    {% set class = "Warrior" %}
    {{ character.name }} is a level {{ to_str(level) }} {{ class }}.
    ```

!!! tip "String Concatenation"
    Use `to_str()` when concatenating non-string values to avoid type errors in template expressions.

---

### len

Returns the length of a collection (string, list, dictionary, etc.).

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `x` | collection | The collection to measure |

!!! return "Returns"

    The number of items in the collection

!!! example "Example: String Length"

    ```jinja2
    {% if len(character.name) > 20 %}
    <|SECTION:NOTE|>
    Character has a very long name, use shortened version when possible.
    <|CLOSE_SECTION|>
    {% endif %}
    ```

!!! example "Example: List Length"

    ```jinja2
    {% set items = ["sword", "shield", "potion"] %}
    {{ character.name }} is carrying {{ len(items) }} items.
    ```

---

### max

Returns the larger of two values.

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `x` | any | First value to compare |
    | `y` | any | Second value to compare |

!!! return "Returns"

    The larger of the two values

!!! example "Example: Limiting Values"

    ```jinja2
    {% set damage = max(1, attack_power - defense) %}
    The attack deals {{ damage }} damage.
    ```

!!! example "Example: Ensuring Minimum Length"

    ```jinja2
    {% set response_length = max(100, desired_length) %}
    Generate a response of approximately {{ response_length }} words.
    ```

---

### min

Returns the smaller of two values.

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `x` | any | First value to compare |
    | `y` | any | Second value to compare |

!!! return "Returns"

    The smaller of the two values

!!! example "Example: Capping Values"

    ```jinja2
    {% set health = min(character.current_health, character.max_health) %}
    Health: {{ health }}/{{ character.max_health }}
    ```

!!! example "Example: Limiting Context Length"

    ```jinja2
    {% set context_lines = min(len(history), 50) %}
    <|SECTION:RECENT HISTORY|>
    {% for message in history[-context_lines:] %}
    {{ message.text }}
    {% endfor %}
    <|CLOSE_SECTION|>
    ```

---

### join

Joins elements of a list into a single string using a separator.

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `x` | list | The list of items to join |
    | `y` | str | The separator string |

!!! return "Returns"

    A string with all items joined by the separator

!!! example "Example: Creating Lists"

    ```jinja2
    {% set abilities = ["fire magic", "healing", "teleportation"] %}
    {{ character.name }} can use: {{ join(abilities, ", ") }}.
    ```

    Output:
    ```
    Alice can use: fire magic, healing, teleportation.
    ```

!!! example "Example: Building Formatted Output"

    ```jinja2
    {% set traits = [] %}
    {% if character.strength > 15 %}{% set _ = traits.append("strong") %}{% endif %}
    {% if character.intelligence > 15 %}{% set _ = traits.append("intelligent") %}{% endif %}
    {% if character.charisma > 15 %}{% set _ = traits.append("charismatic") %}{% endif %}
    
    {% if traits %}
    {{ character.name }} is {{ join(traits, " and ") }}.
    {% endif %}
    ```

---

### data_format_type

Returns the current data format type (JSON or YAML) that the client prefers for structured responses.

!!! payload "Arguments"

    This function takes no arguments.

!!! return "Returns"

    A string: either "json" or "yaml"

!!! example "Example: Format-Specific Instructions"

    ```jinja2
    {% if data_format_type() == "yaml" %}
    <|SECTION:FORMAT NOTE|>
    Please ensure proper YAML indentation (2 spaces).
    <|CLOSE_SECTION|>
    {% else %}
    <|SECTION:FORMAT NOTE|>
    Please ensure valid JSON syntax with proper comma placement.
    <|CLOSE_SECTION|>
    {% endif %}
    ```

!!! note "Client Preference"
    This function checks the client's `data_format` attribute first. If not set, it falls back to the prompt's default data format type.

---

### count_tokens

Counts the number of tokens in a given text string. The text is automatically deduplicated before counting.

!!! payload "Arguments"

    | Argument | Type | Description |
    |----------|------|-------------|
    | `text` | str | The text to count tokens for |

!!! return "Returns"

    The approximate number of tokens in the text

---

### llm_can_be_coerced

Checks whether the current LLM client supports coercion (forcing specific output formats or behaviors).

!!! return "Returns"

    `bool` - True if the client supports coercion, False otherwise

---

### config

Provides access to the global Talemate configuration object.

!!! return "Returns"

    The global configuration object with all Talemate settings

---


## Filters

### condensed

Condenses a string by removing extra whitespace and newlines.

!!! example "Example: Condensed String"

    ```jinja2
    {{ "Hello\n\nWorld" | condensed }}
    ```

    Output:
    ```
    Hello World
    ```