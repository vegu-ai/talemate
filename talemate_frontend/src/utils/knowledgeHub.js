// The World State knowledge hub: which agent settings it offers and how they
// are read off the live agent_status. It never writes; the hub component hands
// a click to the agent drawer's own toggle functions.
import { characterKnowledgeMode } from '@/constants/characterKnowledgeModes';
import {
    configOverrideActive,
    effectiveActionEnabled,
    effectiveConfigValue,
    enabledOverrideActive,
} from '@/constants/sceneAgentSettings';

// `config: null` names the action's own enable switch, offered as the master
// toggle of its group. A config key the status does not carry is left out:
// the backend strips the Standard-only keys in a Character perspectives scene.
export const KNOWLEDGE_TOGGLES = Object.freeze([
    { agent: 'conversation', action: 'character_knowledge', config: null },
    { agent: 'conversation', action: 'character_knowledge', config: 'perspective_filter' },
    { agent: 'conversation', action: 'character_knowledge', config: 'absence_block' },
    { agent: 'conversation', action: 'character_knowledge', config: 'awareness_line' },
    { agent: 'conversation', action: 'character_knowledge', config: 'memory_pass' },
    { agent: 'conversation', action: 'character_knowledge', config: 'ledger' },
    { agent: 'summarizer', action: 'archive', config: 'extract_facts' },
    { agent: 'summarizer', action: 'perceptions', config: 'automatic_repair' },
    { agent: 'memory', action: 'retrieval', config: 'similarity_gate' },
    { agent: 'memory', action: 'topics', config: null },
]);

export const PERSPECTIVES_ANALYSIS_COST = 'Summarizer analysis after each passage';

// carried by the status in both modes, but only runs in Character perspectives
const PERSPECTIVES_ONLY_ACTIONS = new Set(['summarizer.perceptions']);

const AGENT_LABELS = Object.freeze({
    conversation: 'Conversation',
    summarizer: 'Summarizer',
    memory: 'Memory',
    narrator: 'Narrator',
});

// note_on_value keys arrive JSON-serialized, so the bool True reads "true"
function costNote(field) {
    return field.note_on_value?.true?.text || null;
}

/**
 * Group the hub's toggles by agent action, reading each value as the loaded
 * scene sees it (the scene override when one is active). With `perspectives`
 * false the groups that only run in Character perspectives are left out.
 *
 * `agents` is the list AIAgent keeps from agent_status frames: entries carry
 * `name`, `label`, `actions` and `data.scene_overrides`.
 */
export function resolveKnowledgeToggles(agents, { perspectives = true } = {}) {
    const groups = [];
    for (const spec of KNOWLEDGE_TOGGLES) {
        if (!perspectives && PERSPECTIVES_ONLY_ACTIONS.has(`${spec.agent}.${spec.action}`)) continue;
        const agent = (agents || []).find((candidate) => candidate.name === spec.agent);
        const action = agent?.actions?.[spec.action];
        if (!action) continue;
        const overlay = agent.data?.scene_overrides || {};
        let group = groups.find((g) => g.agent === spec.agent && g.action === spec.action);
        if (!group) {
            group = {
                agent: spec.agent,
                agentLabel: agent.label || AGENT_LABELS[spec.agent] || spec.agent,
                action: spec.action,
                label: action.label || spec.action,
                master: false,
                enabled: effectiveActionEnabled(agent.actions, overlay, spec.action),
                enabledOverridden: enabledOverrideActive(overlay, spec.action),
                toggles: [],
            };
            groups.push(group);
        }
        if (spec.config === null) {
            group.master = !!action.can_be_disabled;
            if (spec.costLabel) group.costLabel = spec.costLabel;
            continue;
        }
        const field = action.config?.[spec.config];
        if (!field || field.type !== 'bool') continue;
        group.toggles.push({
            key: spec.config,
            label: field.label || spec.config,
            description: field.description || '',
            value: !!effectiveConfigValue(agent.actions, overlay, `${spec.action}.config.${spec.config}`),
            overridden: configOverrideActive(overlay, spec.action, spec.config),
            costNote: costNote(field),
            ...(spec.costLabel ? { costLabel: spec.costLabel } : {}),
        });
    }
    return groups.filter((group) => group.master || group.toggles.length);
}

/**
 * What the current toggles cost per line, as words: the options that add a
 * request and are on, plus the analysis a Character perspectives scene runs.
 */
export function thoroughnessSummary(groups, perspectives) {
    const extras = perspectives ? [PERSPECTIVES_ANALYSIS_COST] : [];
    for (const group of groups) {
        if (!group.enabled) continue;
        if (!perspectives && PERSPECTIVES_ONLY_ACTIONS.has(`${group.agent}.${group.action}`)) continue;
        if (group.costLabel && (perspectives || groups.find(g => g.agent === 'conversation' && g.action === 'character_knowledge')?.enabled)) extras.push(group.costLabel);
        for (const toggle of group.toggles) {
            if (toggle.costNote && toggle.value) extras.push(toggle.costLabel || toggle.label);
        }
    }
    return {
        mode: characterKnowledgeMode(perspectives).title,
        extras,
        text: extras.length ? `Extra requests: ${extras.join(', ')}` : 'No extra requests per line',
    };
}

// How many of the switches the pane draws are on; an off group turns its own toggles off
export function switchTally(groups) {
    let on = 0;
    let total = 0;
    for (const group of groups || []) {
        if (group.master) {
            total += 1;
            if (group.enabled) on += 1;
        }
        for (const toggle of group.toggles || []) {
            total += 1;
            if (group.enabled && toggle.value) on += 1;
        }
    }
    return { on, total };
}
