/**
 * Routes a clipboard paste that carries an image to one upload zone.
 *
 * A paste event reaches the focused element only, so a zone that nobody
 * focused is served by this one listener on the document.
 */

const targets = [];
let listening = false;

const EDITABLE_SELECTOR = 'input, textarea, select, [contenteditable]:not([contenteditable="false"])';

// the middle, then four inset points, so a zone still counts as reachable when
// a bar or a badge covers its middle
const PROBE_POINTS = [[0.5, 0.5], [0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]];

const CLIPPING_OVERFLOW = ['hidden', 'scroll', 'auto', 'clip'];

function clips(node) {
    const style = getComputedStyle(node);
    return CLIPPING_OVERFLOW.includes(style.overflowX) || CLIPPING_OVERFLOW.includes(style.overflowY);
}

/**
 * The part of the element the user actually sees: its own box, cut down to
 * every ancestor that clips and then to the viewport. Probing the whole box
 * would sample a strip that a scrolled dialog card hides, and refuse a zone
 * whose remaining strip is there to be clicked.
 */
function visibleRect(el) {
    const rect = el.getBoundingClientRect();
    let { left, top, right, bottom } = rect;

    // the root and the body are left to the viewport clamp below: while a
    // dialog blocks scrolling, vuetify shifts the root's box by the scroll
    // position, so its rectangle is nowhere near what it shows
    for (let node = el.parentElement; node && node !== document.body; node = node.parentElement) {
        if (!clips(node)) continue;
        // the padding box, so a probe lands neither on the border nor on the
        // scrollbar
        const box = node.getBoundingClientRect();
        const clipLeft = box.left + node.clientLeft;
        const clipTop = box.top + node.clientTop;
        left = Math.max(left, clipLeft);
        top = Math.max(top, clipTop);
        right = Math.min(right, clipLeft + node.clientWidth);
        bottom = Math.min(bottom, clipTop + node.clientHeight);
    }

    return {
        left: Math.max(left, 0),
        top: Math.max(top, 0),
        right: Math.min(right, window.innerWidth),
        bottom: Math.min(bottom, window.innerHeight),
    };
}

export function clipboardImageFile(clipboardData) {
    if (!clipboardData) return null;

    const files = clipboardData.files || [];
    for (const file of files) {
        if (file && typeof file.type === 'string' && file.type.startsWith('image/')) {
            return file;
        }
    }

    const items = clipboardData.items || [];
    for (const item of items) {
        if (item && item.kind === 'file' && typeof item.type === 'string' && item.type.startsWith('image/')) {
            const file = item.getAsFile();
            if (file) return file;
        }
    }

    return null;
}

export function isEditableTarget(node) {
    if (!node || typeof node.closest !== 'function') return false;
    return !!node.closest(EDITABLE_SELECTOR);
}

/**
 * Whether the user can see the element and click it where it is drawn.
 *
 * The browser's own hit test answers for every covering surface at once: a
 * dialog scrim, an open temporary navigation drawer, a sticky bar. None of
 * those changes anything the element underneath reports about itself, so no
 * style and no class name on the element can answer this.
 */
export function isElementReachable(el) {
    if (!(el instanceof Element) || !el.isConnected) return false;
    if (el.closest('[inert]')) return false;

    const { left, top, right, bottom } = visibleRect(el);
    if (right <= left || bottom <= top) return false;

    return PROBE_POINTS.some(([fx, fy]) => {
        const hit = document.elementFromPoint(left + (right - left) * fx, top + (bottom - top) * fy);
        return !!hit && (hit === el || el.contains(hit));
    });
}

/**
 * Only a zone the user can reach is a candidate, focused or not. Among those,
 * the focused zone wins, so a user can say where a paste goes, and otherwise
 * the one that registered last does.
 */
export function selectPasteTarget(candidates, focusedNodes = []) {
    const usable = candidates.filter(
        (target) => target.isEnabled() && isElementReachable(target.getElement())
    );

    for (const node of focusedNodes) {
        if (!node) continue;
        for (let i = usable.length - 1; i >= 0; i--) {
            const el = usable[i].getElement();
            if (el === node || el.contains(node)) return usable[i];
        }
    }

    return usable.length ? usable[usable.length - 1] : null;
}

function onPaste(event) {
    if (isEditableTarget(event.target)) return;

    const file = clipboardImageFile(event.clipboardData);
    if (!file) return;

    const target = selectPasteTarget(targets, [event.target, document.activeElement]);
    if (!target) return;

    event.preventDefault();
    target.handler(file);
}

export function registerImagePasteTarget({ getElement, handler, isEnabled = () => true }) {
    const target = { getElement, handler, isEnabled };
    targets.push(target);

    if (!listening) {
        document.addEventListener('paste', onPaste);
        listening = true;
    }

    return () => {
        const index = targets.indexOf(target);
        if (index === -1) return;
        targets.splice(index, 1);
        if (targets.length === 0 && listening) {
            document.removeEventListener('paste', onPaste);
            listening = false;
        }
    };
}
