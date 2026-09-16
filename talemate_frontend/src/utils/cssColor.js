let context;

function canvasContext() {
    if (!context) {
        const canvas = document.createElement('canvas');
        canvas.width = 1;
        canvas.height = 1;
        context = canvas.getContext('2d', { willReadFrequently: true });
    }
    return context;
}

// a canvas ignores a fillStyle it cannot parse, so a rejected color reads
// back as whatever was set before it
function accepted(ctx, color) {
    ctx.fillStyle = '#000000';
    ctx.fillStyle = color;
    const first = ctx.fillStyle;
    ctx.fillStyle = '#ffffff';
    ctx.fillStyle = color;
    return first === ctx.fillStyle;
}

// [r, g, b] in 0..255 that the browser paints for `color` over the opaque
// `background` (alpha, named colors and CSS Color 4 spaces included); null for
// a color the browser rejects
export function shownColor(color, background) {
    if (typeof color !== 'string' || !color.trim()) return null;
    const ctx = canvasContext();
    if (!accepted(ctx, color)) return null;
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, 1, 1);
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, 1, 1);
    return Array.from(ctx.getImageData(0, 0, 1, 1).data.slice(0, 3));
}

// black or white, whichever has the higher WCAG contrast ratio against the
// color as shown over the background; null when the color cannot be shown
export function readableTextOn(color, background) {
    const pixel = shownColor(color, background);
    if (!pixel) return null;
    const [r, g, b] = pixel.map((channel) => {
        const c = channel / 255;
        return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
    return (luminance + 0.05) / 0.05 >= 1.05 / (luminance + 0.05) ? '#000000' : '#ffffff';
}
