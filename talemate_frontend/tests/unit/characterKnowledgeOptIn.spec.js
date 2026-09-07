import { describe, expect, it, vi } from 'vitest';
import Setup from '@/components/NewSceneSetupModal.vue';
import Landing from '@/components/SceneLanding.vue';
import SharedWorld from '@/components/WorldStateManagerSceneSharedWorld.vue';

function setup() {
    const vm = { ...Setup.data(), $emit: vi.fn() };
    return vm;
}

describe('character perspectives creation choice', () => {
    it('defaults off and resets after cancel or another creation', () => {
        const vm = setup();
        expect(vm.characterKnowledge).toBe(false);
        vm.characterKnowledge = true;
        Setup.methods.cancel.call(vm);
        expect(vm.$emit).not.toHaveBeenCalledWith('create', expect.anything());
        Setup.watch.modelValue.call(vm, true);
        expect(vm.characterKnowledge).toBe(false);
    });
    it.each([false, true])('forwards the explicit choice %s through the real creation payload', (enabled) => {
        const vm = setup();
        vm.characterKnowledge = enabled;
        Setup.methods.create.call(vm);
        const payload = vm.$emit.mock.calls.find(([type]) => type === 'create')[1];
        const send = vi.fn();
        Landing.methods.createNewScene.call({ $emit: vi.fn(), getWebsocket: () => ({ send }) }, payload);
        expect(JSON.parse(send.mock.calls[0][0])).toMatchObject({
            type: 'load_scene', file_path: '$NEW_SCENE$', scene_initialization: { character_knowledge: enabled },
        });
    });
    it('an omitted choice stays off for existing callers', () => {
        const send = vi.fn();
        Landing.methods.createNewScene.call({ $emit: vi.fn(), getWebsocket: () => ({ send }) }, {});
        expect(JSON.parse(send.mock.calls[0][0]).scene_initialization.character_knowledge).toBe(false);
    });
    it('loading an existing file does not send an activation override', () => {
        const emit = vi.fn();
        Landing.methods.requestSceneLoad.call({ confirmUnsaved: () => true, $emit: emit }, 'legacy.json');
        expect(emit).toHaveBeenCalledWith('request-scene-load', 'legacy.json');
    });
    it.each(['legacy', 'perception'])('shared-world continuation preserves %s mode in its creation payload', (mode) => {
        const send = vi.fn();
        const vm = {
            scene: { data: { knowledge_eligibility: mode, project_name: 'story' } },
            selectedSharedCharacters: ['Alice'], characterData: { Alice: { name: 'Alice' } },
            stopPlaythrough: vi.fn(), getWebsocket: () => ({ send }),
        };
        SharedWorld.methods.confirmCreateNewScene.call(vm);
        expect(JSON.parse(send.mock.calls[0][0])).toMatchObject({
            type: 'load_scene', file_path: '$NEW_SCENE$',
            scene_initialization: { character_knowledge: mode === 'perception', active_characters: ['Alice'] },
        });
    });
});
