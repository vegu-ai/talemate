// read({ scene, agentStatus, templates, narrow }) -> { parts: [{ key, value?, label, icon?, tooltip, muted?, accent?, trailingIcon?, srText? }] }
//                                     or { widget, ...props } for an item the slot renders as a component
// A part reads as a value with a quiet label; a part without a value is a
// muted unavailable or inactive state. An accent part carries a state worth a
// glance, marked by its trailing icon and spoken via srText. A part with an
// icon shows the icon in place of its label, which then names the icon.
import { characterKnowledgeMode } from '@/constants/characterKnowledgeModes';
import { effortMode } from '@/utils/knowledgeEffort';
import { canChangePerspectives, perspectivesEnabled, visualStyleOptions, writingStyleOptions } from '@/utils/sceneSettings';

// circles in the row, the "+N" circle included
export const CHARACTER_CAP = Object.freeze({ wide: 6, narrow: 3 });

const DUE_REASONS = {
    threshold: 'the gathered dialogue passed the threshold',
    time_passage: 'a time passage cut the span',
    presence: 'who is present changed',
};

const HISTORY_STATS = {
    id: 'history_stats',
    label: 'History stats',
    icon: 'mdi-layers-outline',
    description: 'Total messages and summary layers of the scene history.',
    read({ scene }) {
        const stats = scene?.data?.history_stats;
        if (!stats) {
            return unavailable(this, 'History stats unavailable', 'The scene has not reported its history yet.');
        }
        const messages = stats.message_count ?? 0;
        const layers = stats.summary_layers ?? 0;
        return {
            parts: [
                {
                    key: 'messages',
                    value: `${messages}`,
                    label: messages === 1 ? 'message' : 'messages',
                    tooltip: 'Messages in the scene history, including ones already summarized.',
                },
                {
                    key: 'layers',
                    value: `${layers}`,
                    label: layers === 1 ? 'summary layer' : 'summary layers',
                    tooltip: 'Counts the base archive as the first summary layer, then each layered history layer (History tab: Base, Layer 0, ...).',
                },
            ],
        };
    },
};

const SUMMARIZER = {
    id: 'summarizer',
    label: 'Summarizer',
    icon: 'mdi-archive-arrow-down-outline',
    description: 'Dialogue tokens gathered against the summarizer threshold, with a marker when a summary is due.',
    read({ scene, agentStatus }) {
        const agent = agentStatus?.summarizer;
        if (agent && (agent.status === 'uninitialized' || agent.status === 'disabled')) {
            return unavailable(this, 'Summarizer unavailable', 'The summarizer has no ready client.');
        }
        const summarization = scene?.data?.history_stats?.summarization;
        if (!summarization) {
            return unavailable(this, 'Summarizer unavailable', 'The scene has not reported its summarization state yet.');
        }
        if (!summarization.enabled) {
            return unavailable(this, 'Summarization off', 'The summarizer archive action is turned off.');
        }
        const gathered = `${summarization.pending_tokens} of ${summarization.threshold} tokens gathered since the last summary.`;
        const part = {
            key: 'tokens',
            value: `${summarization.pending_tokens} / ${summarization.threshold}`,
            label: 'tokens',
        };
        if (summarization.due) {
            const reason = DUE_REASONS[summarization.due_reason] || 'the archive rule cut the span';
            part.tooltip = `${gathered} A summary is due on the next message: ${reason}.`;
            part.accent = true;
            part.trailingIcon = 'mdi-archive-clock-outline';
            part.srText = `Summary due: ${reason}.`;
        } else {
            part.tooltip = `${gathered} About ${summarization.remaining_tokens} more until they are summarized. A time passage or a change of who is present can summarize earlier.`;
        }
        return { parts: [part] };
    },
};

const ACTIVE_CHARACTERS = {
    id: 'active_characters',
    label: 'Active characters',
    icon: 'mdi-account-group-outline',
    description: 'Portraits of the characters in the scene. Click one to open it in the World Editor.',
    read({ scene, narrow }) {
        const characters = (scene?.data?.characters || []).map(characterBadge);
        if (!characters.length) {
            return unavailable(this, 'No active characters', 'No character is in the scene.');
        }
        const cap = narrow ? CHARACTER_CAP.narrow : CHARACTER_CAP.wide;
        if (characters.length <= cap) {
            return { widget: 'characters', characters, hidden: [] };
        }
        return { widget: 'characters', characters: characters.slice(0, cap - 1), hidden: characters.slice(cap - 1) };
    },
};

const KNOWLEDGE_EFFORT = {
    id: 'knowledge_effort',
    label: 'Knowledge effort',
    icon: 'mdi-head-lightbulb-outline',
    description: "The character knowledge effort of the scene. Click it for the scene's knowledge settings.",
    read({ scene }) {
        return { widget: 'knowledge_effort', mode: effortMode(perspectivesEnabled(scene?.data)) };
    },
};

const WRITING_STYLE = {
    id: 'writing_style',
    label: 'Writing style',
    icon: 'mdi-script-text-outline',
    description: "The scene's writing style template. Click it to pick another one.",
    read({ scene, templates }) {
        return templateSelect({
            setting: 'writing_style_template',
            label: this.label,
            icon: this.icon,
            title: 'Scene writing style',
            templates,
            options: writingStyleOptions(templates),
            current: scene?.data?.writing_style_template,
            unset: { value: 'None', muted: true, tooltip: 'Writing style: none. The scene uses no writing style template. Click to pick one.' },
            tooltip: (name) => `Writing style: ${name}. Click to pick another one.`,
        });
    },
};

const VISUAL_STYLE = {
    id: 'visual_style',
    label: 'Visual style',
    icon: 'mdi-palette-outline',
    description: "The scene's visual art style template. Click it to pick another one.",
    read({ scene, templates }) {
        return templateSelect({
            setting: 'visual_style_template',
            label: this.label,
            icon: this.icon,
            title: 'Scene visual style',
            templates,
            options: visualStyleOptions(templates),
            current: scene?.data?.visual_style_template,
            unset: { value: 'Agent default', muted: false, tooltip: "Visual style: Agent default. Images use the Visualizer's default art style. Click to pick a style for this scene." },
            tooltip: (name) => `Visual style: ${name}. The art style of the images of this scene. Click to pick another one.`,
        });
    },
};

const KNOWLEDGE_MODE = {
    id: 'knowledge_mode',
    label: 'Knowledge mode',
    icon: 'mdi-account-eye-outline',
    description: 'Whether the scene runs Standard character knowledge or Character perspectives.',
    read({ scene }) {
        const perspectives = perspectivesEnabled(scene?.data);
        const where = canChangePerspectives(scene?.data)
            ? 'Change it in World Editor > Scene > Settings > Character perspectives while the story has no history.'
            : 'The story has history, so the mode is fixed. It is chosen in World Editor > Scene > Settings > Character perspectives before play.';
        return {
            parts: [{
                key: 'mode',
                value: perspectives ? 'Perspectives' : 'Standard',
                label: this.label,
                icon: this.icon,
                tooltip: `Knowledge mode: ${characterKnowledgeMode(perspectives).title}. ${where}`,
            }],
        };
    },
};

function unavailable(item, label, tooltip) {
    return { parts: [{ key: `${item.id}-unavailable`, label, tooltip, muted: true }] };
}

// The scene stores '' for a style it never had and null for one cleared on the
// settings page; both read as the unset option.
function templateSelect({ setting, label, icon, title, templates, options, current, unset, tooltip }) {
    const selected = current || null;
    const base = { widget: 'template_select', setting, title, options, selected, label, icon, muted: false };
    if (selected === null) {
        return { ...base, value: unset.value, tooltip: unset.tooltip, muted: unset.muted };
    }
    const option = options.find((candidate) => candidate.value === selected);
    if (option) {
        return { ...base, value: option.title, tooltip: tooltip(option.title) };
    }
    if (!templates?.by_type) {
        return { ...base, value: null, tooltip: `${label}: waiting for the template list.`, muted: true };
    }
    return {
        ...base,
        value: 'Missing template',
        tooltip: `${label}: the scene uses a template that is no longer in your template list. Click to pick another one.`,
    };
}

function characterBadge(character) {
    const name = character.name || '';
    return {
        name,
        color: character.color,
        avatar: character.current_avatar || character.avatar || null,
        initial: (Array.from(name.trim())[0] || '?').toUpperCase(),
    };
}

export const SCENE_HEADER_ITEMS = [HISTORY_STATS, SUMMARIZER, ACTIVE_CHARACTERS, KNOWLEDGE_EFFORT, KNOWLEDGE_MODE, WRITING_STYLE, VISUAL_STYLE];

export const SCENE_HEADER_SLOTS = [
    { id: 'slot_a', label: 'Left of the title', setting: 'scene_header_slot_a' },
    { id: 'slot_b', label: 'Right of the title', setting: 'scene_header_slot_b' },
];

export function findSceneHeaderItem(id, catalog = SCENE_HEADER_ITEMS) {
    return catalog.find((item) => item.id === id) || null;
}

export function resolveSlotItems(ids, context, catalog = SCENE_HEADER_ITEMS) {
    const entries = [];
    for (const id of ids || []) {
        const item = findSceneHeaderItem(id, catalog);
        if (!item) continue;
        entries.push({ id: item.id, label: item.label, ...item.read(context) });
    }
    return entries;
}

export function applySlotEdit(ids, { item, shown }) {
    const current = ids || [];
    if (shown) {
        return current.includes(item) ? current : [...current, item];
    }
    return current.filter((existing) => existing !== item);
}
