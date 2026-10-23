// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { scrollSettingIntoView } from '@/utils/settingsScroll';

function pin({ top, height }) {
    const el = document.createElement('div');
    el.className = 'app-settings-toolbar-pin';
    el.style.top = `${top}px`;
    Object.defineProperty(el, 'offsetHeight', { value: height });
    document.body.appendChild(el);
}

function target({ height }) {
    const el = document.createElement('div');
    Object.defineProperty(el, 'offsetHeight', { value: height });
    el.scrollIntoView = vi.fn();
    document.body.appendChild(el);
    return el;
}

afterEach(() => {
    document.body.innerHTML = '';
});

describe('a settings target scrolls in below the pinned toolbar', () => {
    it('clears the app bar and the toolbar at its current height', () => {
        pin({ top: 72, height: 52 });
        const el = target({ height: 200 });

        scrollSettingIntoView(el);
        expect(el.style.scrollMarginTop).toBe('132px');

        // a toolbar that wrapped to a second row
        document.querySelector('.app-settings-toolbar-pin').remove();
        pin({ top: 72, height: 84 });
        scrollSettingIntoView(el);
        expect(el.style.scrollMarginTop).toBe('164px');
    });

    it('centers a target that fits the visible area', () => {
        pin({ top: 72, height: 52 });
        const el = target({ height: 200 });

        scrollSettingIntoView(el);

        expect(el.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'center' });
    });

    it('aligns the top of a target taller than the visible area', () => {
        pin({ top: 72, height: 52 });
        const el = target({ height: window.innerHeight });

        scrollSettingIntoView(el);

        expect(el.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
    });
});
