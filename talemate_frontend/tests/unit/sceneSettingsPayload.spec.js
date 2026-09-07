import { describe, expect, it, vi } from 'vitest';
import SceneSettings from '@/components/WorldStateManagerSceneSettings.vue';
import {
    PERSPECTIVES_LOCKED_HINT,
    PERSPECTIVES_OPEN_HINT,
    buildSceneSettingsPayload,
    canChangePerspectives,
    perspectivesEnabled,
    perspectivesPayload,
} from '@/utils/sceneSettings';

const sceneData = {
    experimental: true,
    immutable_save: false,
    writing_style_template: 'noir',
    agent_persona_templates: { director: 'stern' },
    visual_style_template: 'ink',
    restore_from: 'save-2.json',
    knowledge_eligibility: 'legacy',
    can_change_knowledge_eligibility: true,
};

describe('buildSceneSettingsPayload', () => {
    it('carries every scene setting the settings page saves', () => {
        expect(buildSceneSettingsPayload(sceneData)).toEqual({
            type: 'world_state_manager',
            action: 'update_scene_settings',
            experimental: true,
            immutable_save: false,
            writing_style_template: 'noir',
            agent_persona_templates: { director: 'stern' },
            visual_style_template: 'ink',
            restore_from: 'save-2.json',
        });
    });

    it('adds the mode only when asked to', () => {
        expect(buildSceneSettingsPayload(sceneData, { knowledgeEligibility: 'perception' }))
            .toMatchObject({ knowledge_eligibility: 'perception' });
        expect(buildSceneSettingsPayload(sceneData, {})).not.toHaveProperty('knowledge_eligibility');
    });

    it('sends an empty persona map for a scene that has none', () => {
        expect(buildSceneSettingsPayload({}).agent_persona_templates).toEqual({});
    });
});

describe('perspectivesPayload', () => {
    it.each([
        [true, 'perception'],
        [false, 'legacy'],
    ])('maps the switch value %s onto the mode %s', (enabled, mode) => {
        expect(perspectivesPayload(sceneData, enabled)).toMatchObject({
            action: 'update_scene_settings',
            knowledge_eligibility: mode,
            writing_style_template: 'noir',
        });
    });

    // The server refuses the change once the scene has history; the hub and
    // the settings page must not send a message the server will reject.
    it.each([false, undefined])('is null when the scene reports availability %s', (available) => {
        expect(perspectivesPayload({ ...sceneData, can_change_knowledge_eligibility: available }, true)).toBeNull();
        expect(canChangePerspectives({ can_change_knowledge_eligibility: available })).toBe(false);
    });

    it('reads the mode off the scene status', () => {
        expect(perspectivesEnabled({ knowledge_eligibility: 'perception' })).toBe(true);
        expect(perspectivesEnabled({ knowledge_eligibility: 'legacy' })).toBe(false);
        expect(perspectivesEnabled(null)).toBe(false);
    });
});

// The settings page is the message's other author: it must send the shared
// shape, so a field added to one caller cannot go missing from the other.
describe('the settings page sends the shared payload', () => {
    it('for a mode change', () => {
        const send = vi.fn();
        const vm = { scene: { data: { ...sceneData } }, getWebsocket: () => ({ send }) };
        vm.update = SceneSettings.methods.update.bind(vm);
        SceneSettings.methods.updateCharacterKnowledge.call(vm, true);
        expect(JSON.parse(send.mock.calls[0][0])).toEqual(perspectivesPayload(sceneData, true));
    });

    it('for any other settings change', () => {
        const send = vi.fn();
        SceneSettings.methods.update.call({ scene: { data: { ...sceneData } }, getWebsocket: () => ({ send }) });
        expect(JSON.parse(send.mock.calls[0][0])).toEqual(buildSceneSettingsPayload(sceneData));
    });

    it.each([
        ['__opt_out__', { agent_settings_file: null }],
        ['__auto__', { agent_settings_opted_out: false }],
        ['overrides.json', { agent_settings_file: 'overrides.json' }],
    ])('for the agent settings link %s, on top of the shared payload', (value, link) => {
        const send = vi.fn();
        SceneSettings.methods.updateAgentSettings.call({ scene: { data: { ...sceneData } }, getWebsocket: () => ({ send }) }, value);
        expect(JSON.parse(send.mock.calls[0][0])).toEqual({ ...buildSceneSettingsPayload(sceneData), ...link });
    });

    it('shows the shared hint texts', () => {
        const data = SceneSettings.data();
        expect(data.PERSPECTIVES_LOCKED_HINT).toBe(PERSPECTIVES_LOCKED_HINT);
        expect(data.PERSPECTIVES_OPEN_HINT).toBe(PERSPECTIVES_OPEN_HINT);
        expect(PERSPECTIVES_LOCKED_HINT).toContain('has history');
    });
});
