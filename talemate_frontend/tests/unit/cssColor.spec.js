// @vitest-environment jsdom

import { beforeAll, describe, expect, it } from 'vitest';
import { readableTextOn, shownColor } from '@/utils/cssColor';
import { installFakeCanvas } from './helpers/fakeCanvas.js';

// Vuetify's default dark and light theme backgrounds
const DARK = '#121212';
const LIGHT = '#ffffff';

beforeAll(() => {
    installFakeCanvas();
});

describe('the color a circle shows', () => {
    it('is the color itself when it is opaque', () => {
        expect(shownColor('#2196F3', DARK)).toEqual([0x21, 0x96, 0xf3]);
        expect(shownColor('navy', LIGHT)).toEqual([0, 0, 128]);
    });

    it('mixes a translucent color with the header background', () => {
        expect(shownColor('#FFFFFF40', DARK)).toEqual([77, 77, 77]);
        expect(shownColor('#FFFFFF40', LIGHT)).toEqual([255, 255, 255]);
        expect(shownColor('#0000', DARK)).toEqual([18, 18, 18]);
        expect(shownColor('rgba(40, 53, 147, 0.5)', LIGHT)).toEqual([148, 154, 201]);
    });

    it('is nothing for a color the browser rejects, or none', () => {
        expect(shownColor('not-a-color', DARK)).toBeNull();
        expect(shownColor('', DARK)).toBeNull();
        expect(shownColor(null, DARK)).toBeNull();
    });
});

describe('readable text on a name color', () => {
    it('picks black or white by the higher WCAG contrast ratio on both themes', () => {
        for (const background of [DARK, LIGHT]) {
            expect(readableTextOn('#283593', background)).toBe('#ffffff');
            expect(readableTextOn('#000', background)).toBe('#ffffff');
            expect(readableTextOn('#C62828', background)).toBe('#ffffff');
            expect(readableTextOn('#fff', background)).toBe('#000000');
            expect(readableTextOn('#F9A825', background)).toBe('#000000');
            expect(readableTextOn('#00BCD4', background)).toBe('#000000');
        }
    });

    it('reads a named color, as the name chip in the dialogue renders it', () => {
        expect(readableTextOn('cornflowerblue', DARK)).toBe('#000000');
        expect(readableTextOn('navy', DARK)).toBe('#ffffff');
        expect(readableTextOn('orange', LIGHT)).toBe('#000000');
    });

    it('chooses against the color the circle shows when the name color has alpha', () => {
        // a quarter-white circle is dark grey on the dark theme and white on the light one
        expect(readableTextOn('#FFFFFF40', DARK)).toBe('#ffffff');
        expect(readableTextOn('#FFFFFF40', LIGHT)).toBe('#000000');
        // a transparent circle shows the header itself
        for (const clear of ['#0000', 'transparent']) {
            expect(readableTextOn(clear, DARK)).toBe('#ffffff');
            expect(readableTextOn(clear, LIGHT)).toBe('#000000');
        }
        expect(readableTextOn('rgba(40, 53, 147, 0.5)', DARK)).toBe('#ffffff');
        expect(readableTextOn('rgba(40, 53, 147, 0.5)', LIGHT)).toBe('#000000');
    });

    it('takes a CSS Color 4 value through the same path', () => {
        expect(readableTextOn('oklch(85% 0.12 90)', DARK)).toBe('#000000');
    });

    it('leaves a color the browser rejects, or none, to the default text color', () => {
        expect(readableTextOn('not-a-color', DARK)).toBeNull();
        expect(readableTextOn('', LIGHT)).toBeNull();
        expect(readableTextOn(undefined, LIGHT)).toBeNull();
    });
});
