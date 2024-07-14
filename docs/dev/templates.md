# Template Overrides

!!! warning "Old documentation"
    This is old documentation and needs to be updated, however may still contain useful information.

## Introduction to Templates

In Talemate, templates are used to generate dynamic content for various agents involved in roleplaying scenarios. These templates leverage the Jinja2 templating engine, allowing for the inclusion of variables, conditional logic, and custom functions to create rich and interactive narratives.

## Template Structure

A typical template in Talemate consists of several sections, each enclosed within special section tags (`<|SECTION:NAME|>` and `<|CLOSE_SECTION|>`). These sections can include character details, dialogue examples, scenario overviews, tasks, and additional context. Templates utilize loops and blocks to iterate over data and render content conditionally based on the task requirements.

## Overriding Templates

Users can customize the behavior of Talemate by overriding the default templates. To override a template, create a new template file with the same name in the `./templates/prompts/{agent}/` directory. When a custom template is present, Jinja2 will prioritize it over the default template located in the `./src/talemate/prompts/templates/{agent}/` directory.

## Creator Agent Templates

The creator agent templates allow for the creation of new characters within the character creator. Following the naming convention `character-attributes-*.jinja2`, `character-details-*.jinja2`, and `character-example-dialogue-*.jinja2`, users can add new templates that will be available for selection in the character creator.

### Requirements for Creator Templates

- All three types (`attributes`, `details`, `example-dialogue`) need to be available for a choice to be valid in the character creator.
- Users can check the human templates for an understanding of how to structure these templates.

### Example Templates

- `src/talemate/prompts/templates/creator/character-attributes-human.jinja2`
- `src/talemate/prompts/templates/creator/character-details-human.jinja2`
- `src/talemate/prompts/templates/creator/character-example-dialogue-human.jinja2`

These example templates can serve as a guide for users to create their own custom templates for the character creator.

### Extending Existing Templates

Jinja2's template inheritance feature allows users to extend existing templates and add extra information. By using the `{% extends "template-name.jinja2" %}` tag, a new template can inherit everything from an existing template and then add or override specific blocks of content.

#### Example

To add a description of a character's hairstyle to the human character details template, you could create a new template like this:

```jinja2
{% extends "character-details-human.jinja2" %}
{% block questions %}
{% if character_details.q("what does "+character.name+"'s hair look like?") -%}
Briefly describe {{ character.name }}'s hair-style using a narrative writing style that reminds of mid 90s point and click adventure games. (2 - 3 sentences).
{% endif %}
{% endblock %}
```

This example shows how to extend the `character-details-human.jinja2` template and add a block for questions about the character's hair. The `{% block questions %}` tag is used to define a section where additional questions can be inserted or existing ones can be overridden.

## Advanced Template Topics

### Jinja2 Functions in Talemate

Talemate exposes several functions to the Jinja2 template environment, providing utilities for data manipulation, querying, and controlling content flow. Here's a list of available functions:

1. `set_prepared_response(response, prepend)`: Sets the prepared response with an optional prepend string. This function allows the template to specify the beginning of the LLM response when processing the rendered template. For example, `set_prepared_response("Certainly!")` will ensure that the LLM's response starts with "Certainly!".
2. `set_prepared_response_random(responses, prefix)`: Chooses a random response from a list and sets it as the prepared response with an optional prefix.
3. `set_eval_response(empty)`: Prepares the response for evaluation, optionally initializing a counter for an empty string.
4. `set_json_response(initial_object, instruction, cutoff)`: Prepares for a JSON response with an initial object and optional instruction and cutoff.
5. `set_question_eval(question, trigger, counter, weight)`: Sets up a question for evaluation with a trigger, counter, and weight.
6. `disable_dedupe()`: Disables deduplication of the response text.
7. `random(min, max)`: Generates a random integer between the specified minimum and maximum.
8. `query_scene(query, at_the_end, as_narrative)`: Queries the scene with a question and returns the formatted response.
9. `query_text(query, text, as_question_answer)`: Queries a text with a question and returns the formatted response.
10. `query_memory(query, as_question_answer, **kwargs)`: Queries the memory with a question and returns the formatted response.
11. `instruct_text(instruction, text)`: Instructs the text with a command and returns the result.
12. `retrieve_memories(lines, goal)`: Retrieves memories based on the provided lines and an optional goal.
13. `uuidgen()`: Generates a UUID string.
14. `to_int(x)`: Converts the given value to an integer.
15. `config`: Accesses the configuration settings.
16. `len(x)`: Returns the length of the given object.
17. `count_tokens(x)`: Counts the number of tokens in the given text.
18. `print(x)`: Prints the given object (mainly for debugging purposes).

These functions enhance the capabilities of templates, allowing for dynamic and interactive content generation.

### Error Handling

Errors encountered during template rendering are logged and propagated to the user interface. This ensures that users are informed of any issues that may arise, allowing them to troubleshoot and resolve problems effectively.

By following these guidelines, users can create custom templates that tailor the Talemate experience to their specific storytelling needs.# Template Overrides in Talemate