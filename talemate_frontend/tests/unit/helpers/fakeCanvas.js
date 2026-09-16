// jsdom has no canvas. This 2D context does what a browser canvas does for
// the colors the specs use: an accepted fillStyle reads back normalized, a
// rejected one leaves the previous value, and fillRect composites source-over
// onto one pixel.
import { vi } from 'vitest';

const NAMED = {
    orange: [255, 165, 0, 1],
    navy: [0, 0, 128, 1],
    cornflowerblue: [100, 149, 237, 1],
    transparent: [0, 0, 0, 0],
    // stands in for a CSS Color 4 value a browser converts to sRGB
    'oklch(85% 0.12 90)': [239, 205, 131, 1],
};

function parse(value) {
    const text = String(value).trim().toLowerCase();
    if (NAMED[text]) return NAMED[text];
    const hex = /^#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/.exec(text)?.[1];
    if (hex) {
        const full = hex.length <= 4 ? Array.from(hex, (digit) => digit + digit).join('') : hex;
        const [r, g, b] = [0, 2, 4].map((start) => parseInt(full.slice(start, start + 2), 16));
        const a = full.length === 8 ? parseInt(full.slice(6, 8), 16) / 255 : 1;
        return [r, g, b, a];
    }
    const rgb = /^rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)$/.exec(text);
    return rgb ? [Number(rgb[1]), Number(rgb[2]), Number(rgb[3]), rgb[4] === undefined ? 1 : Number(rgb[4])] : null;
}

const serialize = ([r, g, b, a]) => (a === 1
    ? `#${[r, g, b].map((c) => c.toString(16).padStart(2, '0')).join('')}`
    : `rgba(${r}, ${g}, ${b}, ${a})`);

export function fakeContext() {
    let style = '#000000';
    let pixel = [0, 0, 0];
    return {
        get fillStyle() {
            return style;
        },
        set fillStyle(value) {
            const parsed = parse(value);
            if (parsed) style = NAMED[String(value).trim().toLowerCase()] ? String(value) : serialize(parsed);
        },
        fillRect() {
            const [r, g, b, a] = parse(style);
            pixel = [r, g, b].map((channel, i) => Math.round(channel * a + pixel[i] * (1 - a)));
        },
        getImageData() {
            return { data: Uint8ClampedArray.from([...pixel, 255]) };
        },
    };
}

export function installFakeCanvas() {
    return vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(fakeContext);
}
