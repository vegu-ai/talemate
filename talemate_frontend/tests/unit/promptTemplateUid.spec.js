import { describe, expect, it } from 'vitest';
import { resolve } from 'node:path';
import { overrideState, worstState } from '@/utils/templateCompatibility.js';
import { newTemplateCategoryHint, newTemplateUid, templateFolder } from '@/utils/promptTemplateUid.js';
import { lift, readSource } from './helpers/liftMethod.js';

const treeSource = readSource(resolve(import.meta.dirname, '../../src/components/prompts/TemplateTree.vue'));
const treeData = lift(treeSource, 'treeData', 'TemplateTree.vue', { overrideState, worstState, templateFolder });
const isOverrideTemplate = lift(treeSource, 'isOverrideTemplate', 'TemplateTree.vue');
const expandToTemplate = lift(treeSource, 'expandToTemplate', 'TemplateTree.vue', { templateFolder });

describe('newTemplateUid', () => {
    it('keys the scene category of the scene group to the root of the scene templates', () => {
        expect(newTemplateUid('scene', 'my-include', { sceneGroup: true })).toBe('.my-include');
    });

    it('keeps an agent category of the scene group in its agent folder', () => {
        expect(newTemplateUid('director', 'my-override', { sceneGroup: true })).toBe('director.my-override');
    });

    it('never turns a category of another group into a root file', () => {
        expect(newTemplateUid('scene', 'my-override')).toBe('scene.my-override');
        expect(newTemplateUid('narrator', 'my-override')).toBe('narrator.my-override');
    });
});

describe('newTemplateCategoryHint', () => {
    it('says what each category of the scene group makes', () => {
        expect(newTemplateCategoryHint('scene', { sceneGroup: true })).toContain('Direction instruction template');
        expect(newTemplateCategoryHint('director', { sceneGroup: true })).toContain('Overrides the director prompt template');
    });

    it('stays generic before a category is picked and in the other groups', () => {
        const generic = 'Select the category this template belongs to';
        expect(newTemplateCategoryHint(null, { sceneGroup: true })).toBe(generic);
        expect(newTemplateCategoryHint('scene')).toBe(generic);
        expect(newTemplateCategoryHint('narrator')).toBe(generic);
    });
});

describe('the folders of the template tree', () => {
    const template = (agent, name) => ({
        agent,
        name,
        uid: `${agent}.${name}`,
        source_group: 'scene',
        available_in: ['scene'],
    });

    it('keeps root-level scene files under "scene" and agent-scene files under their own folder', () => {
        const context = {
            templates: [template('', 'shared'), template('scene', 'shared'), template('director', 'shared')],
            prioritizeScene: true,
            isOverrideTemplate,
        };

        const { items } = treeData.call(context);

        expect(items.map((item) => item.name)).toEqual(['scene', 'director', 'scene (agent)']);
        expect(items[0].children.map((child) => child.uid)).toEqual(['.shared']);
        expect(items[2].children.map((child) => child.uid)).toEqual(['scene.shared']);
    });

    it('opens the folder a template sits in', () => {
        const context = { openedFolders: [] };

        expandToTemplate.call(context, '.shared');
        expandToTemplate.call(context, 'scene.shared');

        expect(context.openedFolders).toEqual(['scene', 'scene (agent)']);
    });
});
