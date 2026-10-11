// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import Description from '@/components/WorldStateManagerCharacterDescription.vue';
import SceneOutline from '@/components/WorldStateManagerSceneOutline.vue';
import { readSource } from './helpers/liftMethod';
import { optionsHost } from './helpers/optionsHost';

// The user presses Ctrl+Enter, the completion lands, and the user clicks away
// without typing: the field's own blur handler is all that can save it.
const hosts = [
    {
        name: 'character Description',
        component: Description,
        path: 'src/components/WorldStateManagerCharacterDescription.vue',
        blur: '@blur="onBlurSave"',
        open: (vm) => Description.watch.immutableCharacter.handler.call(vm, { name: 'Mara', description: 'Kept the light.' }),
        complete: (vm) => vm.sendAutocompleteRequest(),
        leave: (vm) => vm.onBlurSave(),
        shown: (vm) => vm.character.description,
        save: { action: 'update_character_description', value: 'Kept the light. Then it failed.' },
    },
    {
        name: 'Scene introduction',
        component: SceneOutline,
        path: 'src/components/WorldStateManagerSceneOutline.vue',
        blur: '@blur="onIntroBlurSave"',
        open: (vm) => SceneOutline.watch.immutableScene.handler.call(vm, { name: 'Lighthouse', data: { title: 'Lighthouse', intro: 'Kept the light.' } }),
        complete: (vm) => vm.sendAutocompleteRequestForIntro(),
        leave: (vm) => vm.onIntroBlurSave(),
        shown: (vm) => vm.scene.data.intro,
        save: { action: 'update_scene_outline', value: 'Kept the light. Then it failed.', field: 'intro' },
    },
];

describe.each(hosts)('Ctrl+Enter completion in $name', (kind) => {
    function world() {
        const { vm, sent } = optionsHost(kind.component, { description: { focus() {} }, intro: { focus() {} } });
        kind.open(vm);
        return { vm, sent };
    }

    it('is saved when the field is left without typing', () => {
        const { vm, sent } = world();
        kind.complete(vm);
        vm.pendingCompletion(' Then it failed.', { hintsEnabled: false });
        expect(kind.shown(vm)).toBe(kind.save.value);
        kind.leave(vm);
        expect(sent).toHaveLength(1);
        expect(sent[0].action).toBe(kind.save.action);
        expect(sent[0][kind.save.field || 'value']).toBe(kind.save.value);
    });

    it('sends nothing when the field is left with no completion and no typing', () => {
        const { vm, sent } = world();
        kind.leave(vm);
        expect(sent).toEqual([]);
    });

    it('leaves through the blur handler the template binds', () => {
        expect(readSource(kind.path)).toContain(kind.blur);
    });
});
