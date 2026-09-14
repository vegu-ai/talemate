import { describe, expect, it, vi } from 'vitest';
import Settings from '@/components/AppSettingsAgents.vue';

const edit = { actions: { character_knowledge: { config: { ledger: { value: true } } } } };

// The Agents page with one buffered override on a saved scene that has no
// agent-settings file linked yet, so the next save asks for a file name.
// `saveResult` may be a function, to make the dialog throw.
function page({ immutable = true, saveResult = { status: 'saved' } } = {}) {
    const sceneData = {
        filename: 'stock.json',
        project_name: 'proj',
        immutable_save: immutable,
        agent_settings_file: null,
    };
    const sent = [];
    const vm = {
        ...Settings.data(),
        liveAgents: { conversation: { name: 'conversation', data: { scene_overrides: {} } } },
        sceneOverrideBuffer: { conversation: structuredClone(edit) },
        scene: () => ({ data: sceneData }),
        getWebsocket: () => ({ readyState: WebSocket.OPEN, send: (payload) => sent.push(JSON.parse(payload)) }),
        // the scene status of the copy arrives after the save answer, so the
        // page still reads the read-only scene when it commits
        requestSceneSave: vi.fn(async () => (typeof saveResult === 'function' ? saveResult() : saveResult)),
        $emit: vi.fn(),
        $refs: { namingDialog: { openDialog: vi.fn() } },
    };
    for (const [key, method] of Object.entries(Settings.methods)) vm[key] = method.bind(vm);
    for (const [key, getter] of Object.entries(Settings.computed)) Object.defineProperty(vm, key, { get: () => getter.call(vm) });
    return { vm, sent };
}

async function saveWithName(vm, filename) {
    const preparing = vm.prepareExtraChanges();
    expect(vm.$refs.namingDialog.openDialog).toHaveBeenCalledTimes(1);
    vm.onNamingConfirm(filename);
    return preparing;
}

describe('a read-only scene links another file through a Save As copy', () => {
    it('opens Save As after the name, then commits the link to the copy', async () => {
        const { vm, sent } = page();

        expect(await saveWithName(vm, 'custom.json')).toBe(true);
        expect(vm.requestSceneSave).toHaveBeenCalledTimes(1);

        vm.commitExtraChanges();
        expect(sent).toEqual([expect.objectContaining({
            action: 'save_scene_overrides', agent_type: 'conversation', filename: 'custom.json', override: edit,
        })]);
    });

    it.each([
        ['cancelled', { status: 'cancelled' }, /Save As cancelled/],
        ['failed', { status: 'failed', message: 'disk full' }, /Save As failed \(disk full\)/],
        ['thrown', () => { throw new Error('no dialog'); }, /Save As failed \(no dialog\)/],
    ])('aborts the save when Save As is %s, keeping the edits', async (_, saveResult, message) => {
        const { vm, sent } = page({ saveResult });

        expect(await saveWithName(vm, 'custom.json')).toBe(false);

        expect(vm.pendingFilename).toBeNull();
        expect(vm.$emit).toHaveBeenCalledWith('extra-error', expect.stringMatching(message));
        expect(vm.sceneOverrideBuffer.conversation).toEqual(edit);
        expect(vm.hasPendingSceneOverrides).toBe(true);
        expect(sent).toEqual([]);
    });

    it('tells the user about the copy in the name prompt', () => {
        expect(page().vm.namingInstructions).toMatch(/read-only.*Save As/s);
        expect(page({ immutable: false }).vm.namingInstructions).not.toMatch(/read-only/);
    });
});

describe('links that need no copy go straight out', () => {
    it.each([
        ['the default name on a read-only scene', true, 'agent-settings.json'],
        ['any name on a scene that saves in place', false, 'custom.json'],
    ])('%s', async (_, immutable, filename) => {
        const { vm, sent } = page({ immutable });

        expect(await saveWithName(vm, filename)).toBe(true);
        expect(vm.requestSceneSave).not.toHaveBeenCalled();

        vm.commitExtraChanges();
        expect(sent[0].filename).toBe(filename);
    });

    it('cancelling the name prompt still opens no Save As', async () => {
        const { vm } = page();
        const preparing = vm.prepareExtraChanges();
        vm.onNamingCancel();

        expect(await preparing).toBe(false);
        expect(vm.requestSceneSave).not.toHaveBeenCalled();
    });
});
