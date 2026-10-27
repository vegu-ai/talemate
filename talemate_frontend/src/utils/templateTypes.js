import { colorForTemplate, iconForTemplate } from './templateMappings.js';

// Every template type the Templates page offers.
const TEMPLATE_TYPES = {
    state_reinforcement: {
        title: "State reinforcement",
        help: "State reinforcement templates are used to quickly (or even automatically) setup common attribues and states you want to track for characters or the world itself. They revolve around a question, statement or attribute name that you want to track for a character. The AI will use this template to generate content that matches the query, based on the current progression of the scene.",
    },
    character_attribute: {
        title: "Character attribute",
        help: "Character attribute templates are used to define attributes that a character can have. They can be used to define character traits, skills, or other properties. The AI will use this template to generate content that matches the attribute, based on the current progression of the scene or their backstory.",
    },
    character_detail: {
        title: "Character detail",
        help: "Character detail templates are used to define details about a character. They generally are longer form questions or statements that can be used to flesh out a character's backstory or personality. The AI will use this template to generate content that matches the detail, based on the current progression of the scene or their backstory.",
    },
    spices: {
        title: "Spice collection",
        help: "Spice collections are used to define a set of instructions that can be applied during the generation of character attributes or details. They can be used to add a bit of randomness or unexpectedness. A template must explicitly support spice to be able to use a spice collection.",
    },
    writing_style: {
        title: "Writing style",
        help: "Writing style templates are used to define a writing style that can be applied to the generated content. They can be used to add a specific flavor or tone. A template must explicitly support writing styles to be able to use a writing style template.",
    },
    visual_style: {
        title: "Visual style",
        help: "Visual style templates define how image prompts are constructed (positive/negative prefixes and suffixes) and the prompting type (keywords vs descriptive).",
    },
    visual_finalizer: {
        title: "Visual prompt finalizer",
        help: "Visual prompt finalizer templates define a reusable set of post-processing actions (exact, fuzzy or regex match and replace, or AI processing) applied to image generation prompts. Select one as the preset in the visualizer agent's Prompt Finalization settings.",
    },
    agent_persona: {
        title: "Agent persona",
        help: "Agent personas define how an agent should present and behave in prompts (tone, perspective, style). Assign a persona per agent in Scene Settings. (Currently director only)",
    },
    scene_type: {
        title: "Scene type",
        help: "Scene type templates are used to define different types of scenes that can be played in your game. Each scene type has different rules and constraints that guide the generation and flow of the scene.",
    },
    scene_tool_shortcut: {
        title: "Scene tool shortcut",
        help: "Scene tool shortcut templates package a scene tool action together with a label, an icon and canned instructions. Installing one adds the shortcut to your scene tools menu, where it can be run with a single click.",
    },
    theme: {
        title: "Theme",
        help: "Theme templates hold a complete set of colors for the app, its surfaces, the scene messages and the chats, together with how message text is styled. Applying one repaints Talemate with those colors. The node editor canvas keeps its own colors, but the borders of the module tiles in its library follow the App panel.",
    },
};

export function templateTypeItems() {
    return Object.entries(TEMPLATE_TYPES)
        .map(([value, { title, help }]) => ({
            value,
            title,
            help,
            icon: iconForTemplate({ template_type: value }),
            color: colorForTemplate({ template_type: value }),
        }))
        .sort((a, b) => a.title.localeCompare(b.title));
}

export function templateTypeHelp(templateType) {
    return TEMPLATE_TYPES[templateType]?.help;
}

export function templateTypeTitle(templateType) {
    return TEMPLATE_TYPES[templateType]?.title ?? templateType;
}
