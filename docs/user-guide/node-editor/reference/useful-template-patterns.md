# Template Pattern Cheat Sheet

### Scene Context Inclusion

Include scene history with budget control:
```
{% set history = scene.context_history(budget=budget, min_dialogue=20, sections=False) %}
<|SECTION:SCENE|>
{% for scene_context in history -%}
{{ scene_context }}
{% endfor %}
<|CLOSE_SECTION|>
```

**Variables explained:**

- `budget` - Maximum token allocation for context (`max_tokens` will be available and hold the total token budget)
- `min_dialogue` - Minimum number of dialogue lines to include
- `scene` - The current scene object (automatically available)

**Reusable template:** Include `scene-context.jinja2` instead of writing this manually.

### Memory Context Inclusion

Retrieve relevant memories based on context:
```
{% set memory_stack = agent_action("narrator", "rag_build", prompt=memory_prompt, sub_instruction=memory_goal) %}
{% if memory_stack %}
<|SECTION:POTENTIALLY RELEVANT INFORMATION|>
{%- for memory in memory_stack -%}
{{ memory|condensed }}
{% endfor -%}
<|CLOSE_SECTION|>
{% endif %}
```

**Variables explained:**

- `memory_prompt` - The text to search memories for
- `memory_goal` - Optional specific goal for memory retrieval
- `agent_action()` - Built-in function to call agent actions

**Reusable template:** Include `memory-context.jinja2` for standard memory inclusion.

### Character Context Inclusion

Include character information with conditional detail:
```
<|SECTION:CHARACTERS|>
{% for character in scene.characters %}
### {{ character.name }}
{% if max_tokens > 6000 -%}
{# we have lots of space so print the whole character sheet #}
{{ character.sheet }}
{% else -%}
{# we have limited space so print the bare minimum and then query memory for personality #}
{# bare minimum attributes that are guaranteed to be available #}
{{ character.filtered_sheet(['name', 'gender', 'age']) }}
{# query memory for personality #}
{{ query_memory("what is "+character.name+"'s personality?", as_question_answer=False) }}
{% endif %}
{{ character.description }}
{% endfor %}
<|CLOSE_SECTION|>
```

**Variables explained:**

- `scene.characters` - List of all characters in the scene
- `max_tokens` - Available token budget (from agent client)
- `character.sheet` - Full character attributes
- `character.filtered_sheet()` - Subset of character attributes
- `query_memory()` - Built-in function to query memory

**Reusable template:** Include `character-context.jinja2` for standard character listing.

### Including other templates

```
{% include "memory-context.jinja2" %}
{% with budget=budget %}{% include "scene-context.jinja2" %}{% endwith %}
```

The `{% include %}` directive allows you to reuse existing templates. Common includes:

- `scene-context.jinja2` - Standard scene history
- `memory-context.jinja2` - Memory retrieval
- `character-context.jinja2` - Character listings
- `extra-context.jinja2` - Additional context like pins and reinforcements
- `scene-intent.jinja2` - Scene intention

### Conditional sections based on token budget

```
{% if max_tokens > 6000 -%}
  {{ detailed_content }}
{% else -%}
  {{ condensed_content }}
{% endif %}
```

### Response scaffolding

You can use the `{{ bot_token }}` variable to separate the prompt and any response scaffolding you want to do.

!!! note "Scaffolding?"

    Scaffolding is a technique where you provide the beginning of the response, and then let the agent continue.

    This can be useful when you want to coerce the agent down a specific path or formatting.

```
<|SECTION:TASK|>
Analyze the current moment in the scene and then make a prediction about what will happen next.

Do your analysis first!

Provide your response in the following format:

ANALYSIS: .. your analysis ..

PREDICTION: .. your prediction ..
<|CLOSE_SECTION|>
{{ bot_token }}ANALYSIS:
```

Its important to note that with this approach, anything you put after the `{{ bot_token }}` will be missing from the response. So in this example the `ANALYSIS:` string will not be part of the response.

If you need it, you can instead use the `set_prepared_response` function.

```
<|SECTION:TASK|>
Analyze the current moment in the scene and then make a prediction about what will happen next.

Do your analysis first!

Provide your response in the following format:

ANALYSIS: .. your analysis ..

PREDICTION: .. your prediction ..
<|CLOSE_SECTION|>
{{ set_prepared_response("ANALYSIS: ") }}
```

### Response scaffolding for data structures

Scaffolding can be exceptionally helpful if you are prompting the agent to generate a data structure and nothing else, because you can simply coerce it to start with the data structure you want.

```
<|SECTION:TASK|>
Generate a list of objects in the scene, provide a name and description for each object.


  ```json
  {
    "objects": [
      {
        "name": "an old shelf",
        "description": "a shelf that is old and has a few scratches on it"
      },
      {
        "name": "a dirty carpet",
        "description": "a carpet that is dirty and has a few stains on it"
      }
    ]
  }
  ```

<|CLOSE_SECTION|>
{{ set_data_response({"objects": [{"name":""}]}) }}
```