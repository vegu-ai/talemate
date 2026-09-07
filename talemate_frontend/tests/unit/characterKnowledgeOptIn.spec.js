import { describe, expect, it, vi } from 'vitest';
import Setup from '@/components/NewSceneSetupModal.vue';
import Landing from '@/components/SceneLanding.vue';
import CardImport from '@/components/CharacterCardImport.vue';
import SceneSettings from '@/components/WorldStateManagerSceneSettings.vue';
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


function cardModel() {
    const vm = { ...CardImport.data(), appConfig: () => ({}), getWebsocket: () => ({ send: vi.fn() }) };
    for (const [name, method] of Object.entries(CardImport.methods)) vm[name] = method.bind(vm);
    return vm;
}

describe('card import character perspectives', () => {
    it.each(['cancel', 'close'])('resets the choice on %s and reopen', async (action) => {
        const vm = cardModel();
        expect(vm.characterKnowledge).toBe(false);
        const pending = vm.open();
        vm.characterKnowledge = true;
        if (action === 'cancel') vm.cancel();
        else vm.onDialogClose(false);
        expect(await pending).toEqual({ confirmed: false });
        expect(vm.characterKnowledge).toBe(false);
        vm.characterKnowledge = true;
        const reopened = vm.open();
        expect(vm.characterKnowledge).toBe(false);
        vm.cancel();
        await reopened;
    });
    it.each([false, true])('returns choice %s alongside import options', async enabled => {
        const vm = cardModel();
        const pending = vm.open();
        vm.characterKnowledge = enabled;
        vm.selectedCharacterNames = ['Hero'];
        vm.playerCharacterMode = 'existing';
        vm.playerCharacterExisting = 'Hero';
        vm.confirm();
        expect(await pending).toMatchObject({ confirmed: true, characterKnowledge: enabled, options: { selected_character_names: ['Hero'] } });
    });
    it.each([false, true])('forwards choice %s from uploaded and path-based JSON cards', async enabled => {
        for (const upload of [false, true]) {
            const send = vi.fn();
            const vm = { isCharacterCardJson: () => true, showCharacterCardImportModal: async () => ({ confirmed: true, options: {}, characterKnowledge: enabled }), getWebsocket: () => ({ send }), $emit: vi.fn() };
            await Landing.methods.processJsonFile.call(vm, {}, upload ? null : 'card.json', upload ? 'data:application/json;base64,e30=' : null, 'card.json');
            expect(JSON.parse(send.mock.calls[0][0]).scene_initialization).toEqual({ character_knowledge: enabled, character_card_import_options: {} });
        }
    });
    it.each([false, true])('forwards choice %s from path-based image cards', async enabled => {
        const send = vi.fn();
        const vm = { confirmUnsaved: () => true, showCharacterCardImportModal: async () => ({ confirmed: true, options: {}, characterKnowledge: enabled }), getWebsocket: () => ({ send }), $emit: vi.fn() };
        await Landing.methods.loadFromPath.call(vm, 'card.webp');
        expect(JSON.parse(send.mock.calls[0][0]).scene_initialization.character_knowledge).toBe(enabled);
    });
    it.each([false, true])('forwards choice %s from uploaded image cards', async enabled => {
        const send = vi.fn();
        let reader;
        vi.stubGlobal('FileReader', class {
            constructor() { reader = this; this.result = 'data:image/png;base64,card'; }
            readAsDataURL() {}
        });
        try {
            const vm = { confirmUnsaved: () => true, showCharacterCardImportModal: async () => ({ confirmed: true, options: {}, characterKnowledge: enabled }), getWebsocket: () => ({ send }), $emit: vi.fn() };
            Landing.methods.loadFromFile.call(vm, { type: 'image/png', name: 'card.png' });
            await reader.onload();
            expect(JSON.parse(send.mock.calls[0][0]).scene_initialization.character_knowledge).toBe(enabled);
        } finally {
            vi.unstubAllGlobals();
        }
    });
});

describe('scene settings character perspectives', () => {
    it.each([false, true])('sends choice %s without optimistically changing the server mode', enabled => {
        const send = vi.fn();
        const mode = enabled ? 'legacy' : 'perception';
        const vm = { scene: { data: { can_change_knowledge_eligibility: true, knowledge_eligibility: mode } }, getWebsocket: () => ({ send }) };
        vm.update = SceneSettings.methods.update.bind(vm);
        SceneSettings.methods.updateCharacterKnowledge.call(vm, enabled);
        expect(JSON.parse(send.mock.calls[0][0])).toMatchObject({ action: 'update_scene_settings', knowledge_eligibility: enabled ? 'perception' : 'legacy' });
        expect(vm.scene.data.knowledge_eligibility).toBe(mode);
    });
    it.each([false, undefined])('does not send changes when availability is %s', available => {
        const vm = { scene: { data: { can_change_knowledge_eligibility: available } }, update: vi.fn() };
        SceneSettings.methods.updateCharacterKnowledge.call(vm, true);
        expect(vm.update).not.toHaveBeenCalled();
    });
    it('omits the mode from unrelated settings updates', () => {
        const send = vi.fn();
        SceneSettings.methods.update.call({ scene: { data: { knowledge_eligibility: 'perception' } }, getWebsocket: () => ({ send }) });
        expect(JSON.parse(send.mock.calls[0][0])).not.toHaveProperty('knowledge_eligibility');
    });
});
