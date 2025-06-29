# Adding a new world-state template

I am writing this up as I add phrase detection functionality to the `Writing Style` template, so that in the future, hopefully when new template types need to be added this document can just given to the LLM of the month, to do it.

## Introduction

World state templates are reusable components that plug in various parts of talemate.

At this point there are following types:

- Character Attribute
- Character Detail
- Writing Style
- Spice (for randomization of content during generation)
- Scene Type
- State Reinforcement

Basically whenever we want to add something reusable and customizable by the user, a world state template is likely a good solution.

## Steps to creating a new template type

### 1. Add a pydantic schema (python)

In `src/talemate/world_state/templates` create a new `.py` file with reasonable name. 

In this example I am extending the `Writing Style` template to include phrase detection functionality, which will be used by the `Editor` agent to detect certain phrases and then act upon them. 

There already is a `content.py` file - so it makes sense to just add this new functionality to this file.

```python
class PhraseDetection(pydantic.BaseModel):
    phrase: str
    instructions: str
    # can be "unwanted" for now, more added later
    classification: Literal["unwanted"] = "unwanted"

@register("writing_style")
class WritingStyle(Template):
    description: str | None = None
    phrases: list[PhraseDetection] = pydantic.Field(default_factory=list)

    def render(self, scene: "Scene", character_name: str):
        return self.formatted("instructions", scene, character_name)
```

If I were to create a new file I'd still want to read one of the existing files first to understand imports and style.

### 2. Add a vue component to allow management (vue, js)

Next we need to add a new vue component that exposes a UX for us to manage this new template type.

For this I am creating `talemate_frontend/src/components/WorldStateManagerTemplateWritingStyle.vue`.

## Bare Minimum Understanding for New Template Components

When adding a new component for managing a template type, you need to understand:

### Component Structure

1. **Props**: The component always receives an `immutableTemplate` prop with the template data.
2. **Data Management**: Create a local copy of the template data for editing before saving back.
3. **Emits**: Use the `update` event to send modified template data back to the parent.

### Core Implementation Requirements

1. **Template Properties**: Always include fields for `name`, `description`, and `favorite` status.
2. **Data Binding**: Implement two-way binding with `v-model` for all editable fields.
3. **Dirty State Tracking**: Track when changes are made but not yet saved.
4. **Save Method**: Implement a `save()` method that emits the updated template.

### Component Lifecycle

1. **Initialization**: Use the `created` hook to initialize the local template copy.
2. **Watching for Changes**: Set up a watcher for the `immutableTemplate` to handle external updates.

### UI Patterns

1. **Forms**: Use Vuetify form components with consistent validation.
2. **Actions**: Provide clear user actions for editing and managing template items.
3. **Feedback**: Give visual feedback when changes are being made or saved.

The WorldStateManagerTemplate components follow a consistent pattern where they:
- Display and edit general template metadata (name, description, favorite status)
- Provide specialized UI for the template's unique properties
- Handle the create, read, update, delete (CRUD) operations for template items
- Maintain data integrity by properly handling template updates

You absolutely should read an existing component like `WorldStateManagerTemplateWritingStyle.vue` first to get a good understanding of the implementation.

## Integrating with WorldStateManagerTemplates

After creating your template component, you need to integrate it with the WorldStateManagerTemplates component:

### 1. Import the Component

Edit `talemate_frontend/src/components/WorldStateManagerTemplates.vue` and add an import for your new component:

```javascript
import WorldStateManagerTemplateWritingStyle from './WorldStateManagerTemplateWritingStyle.vue'
```

### 2. Register the Component

Add your component to the components section of the WorldStateManagerTemplates:

```javascript
components: {
  // ... existing components
  WorldStateManagerTemplateWritingStyle
}
```

### 3. Add Conditional Rendering

In the template section, add a new conditional block to render your component when the template type matches:

```html
<WorldStateManagerTemplateWritingStyle v-else-if="template.template_type === 'writing_style'"
    :immutableTemplate="template"
    @update="(template) => applyAndSaveTemplate(template)"
/>
```

### 4. Add Icon and Color

Add cases for your template type in the `iconForTemplate` and `colorForTemplate` methods:

```javascript
iconForTemplate(template) {
    // ... existing conditions
    else if (template.template_type == 'writing_style') {
        return 'mdi-script-text';
    }
    return 'mdi-cube-scan';
},

colorForTemplate(template) {
    // ... existing conditions
    else if (template.template_type == 'writing_style') {
        return 'highlight5';
    }
    return 'grey';
}
```

### 5. Add Help Message

Add a help message for your template type in the `helpMessages` object in the data section:

```javascript
helpMessages: {
    // ... existing messages
    writing_style: "Writing style templates are used to define a writing style that can be applied to the generated content. They can be used to add a specific flavor or tone. A template must explicitly support writing styles to be able to use a writing style template.",
}
```

### 6. Update Template Type Selection

Add your template type to the `templateTypes` array in the data section:

```javascript
templateTypes: [
    // ... existing types
    { "title": "Writing style", "value": 'writing_style'},
]
```
