import vueParser from 'vue-eslint-parser';

const MESSAGE =
    'crypto.randomUUID() only works in secure contexts; use newUuid() from @/utils/uuid instead.';

const rules = {
    'no-restricted-properties': ['error', { property: 'randomUUID', message: MESSAGE }],
    'no-restricted-globals': ['error', { name: 'randomUUID', message: MESSAGE }],
};

export default [
    {
        ignores: ['dist/**', 'public/**'],
    },
    {
        // this config enables no rules beyond the two below, so the
        // eslint-disable comments the source already carries name rules that
        // are off here and would report as unused
        linterOptions: {
            reportUnusedDisableDirectives: 'off',
        },
    },
    {
        files: ['**/*.js', '**/*.mjs'],
        rules,
    },
    {
        files: ['**/*.vue'],
        languageOptions: {
            parser: vueParser,
        },
        rules,
    },
];
