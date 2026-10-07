// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { createApp, defineComponent, h } from 'vue';
import UxField from '@/components/UxField.vue';

const CHOICES = [
    { label: 'none', value: 'none', description: 'Sends no effort field.' },
    { label: 'reasoning', value: 'reasoning' },
];

const mounted = [];
afterEach(() => { for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); } });

// renders the item slot for every choice the way Vuetify does
function listStub(name) {
    return defineComponent({
        props: ['items', 'modelValue'],
        setup(props, { slots }) {
            return () => h('div', { 'data-widget': name }, (props.items || []).map(raw => slots.item?.({
                props: { title: raw.label, value: raw.value },
                internalItem: { raw },
            })));
        },
    });
}

const ListItemStub = defineComponent({
    inheritAttrs: false,
    setup: (_, { attrs }) => () => h('div', {
        class: 'item',
        'data-title': attrs.title,
        'data-subtitle': attrs.subtitle ?? '',
        'data-lines': attrs.lines,
    }),
});

function mount(field) {
    const app = createApp({ render: () => h(UxField, { field, modelValue: field.value }) });
    app.component('VSelect', listStub('select'));
    app.component('VAutocomplete', listStub('autocomplete'));
    app.component('VListItem', ListItemStub);
    const host = document.createElement('div');
    document.body.appendChild(host);
    app.mount(host);
    mounted.push([app, host]);
    return host;
}

const items = host => [...host.querySelectorAll('.item')].map(({ dataset }) => ({
    title: dataset.title,
    subtitle: dataset.subtitle,
    lines: dataset.lines,
}));

describe('UxField choice subtitles', () => {
    it.each([
        ['select', 'text'],
        ['autocomplete', 'autocomplete'],
    ])('shows a choice description as the subtitle in a %s', (widget, type) => {
        const host = mount({ type, label: 'Format', value: 'none', choices: CHOICES });
        expect(host.querySelector(`[data-widget="${widget}"]`)).not.toBeNull();
        expect(items(host)).toEqual([
            { title: 'none', subtitle: 'Sends no effort field.', lines: 'two' },
            { title: 'reasoning', subtitle: '', lines: 'one' },
        ]);
    });
});
