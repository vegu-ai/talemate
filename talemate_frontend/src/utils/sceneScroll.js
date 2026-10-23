/**
 * The story's auto-scroll lines the message input up with the bottom edge,
 * which leaves the 16px padding below the scene out of view; a reader there is
 * at the bottom.
 */
export const AT_BOTTOM_SLACK = 24;

// Chromium's own line and page steps.
const LINE_STEP = 40;
const PAGE_FRACTION = 0.875;

const PAGE_KEYS = ['PageUp', 'PageDown', 'Home', 'End'];
// keys a focused control acts on itself (a button presses, a tab moves), so
// they scroll only from the body
const BODY_KEYS = [' ', 'ArrowUp', 'ArrowDown'];

// elements that take text and so keep the page keys; a checkbox or a button
// does not. Narrower than imagePaste's EDITABLE_SELECTOR, which excludes every
// input from paste.
const TAKES_TEXT = [
    'input:not([type="checkbox"], [type="radio"], [type="button"], [type="submit"], [type="reset"], [type="color"], [type="file"], [type="image"])',
    'textarea',
    'select',
    '[contenteditable]:not([contenteditable="false"])',
].join(', ');
const MENU = '.v-overlay, [role="menu"], [role="listbox"], [role="dialog"]';

/** How far the scroller is from its bottom, or null when it is further than the slack. */
export function offsetAtBottom(scroller) {
    const offset = scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop;
    return offset <= AT_BOTTOM_SLACK ? Math.max(0, offset) : null;
}

export function setBottomOffset(scroller, offset) {
    scroller.scrollTop = scroller.scrollHeight - scroller.clientHeight - offset;
}

function scrollsItself(el) {
    const overflow = getComputedStyle(el).overflowY;
    return (overflow === 'auto' || overflow === 'scroll') && el.scrollHeight > el.clientHeight;
}

function isPage(el) {
    return el === document.body || el === document.documentElement;
}

/**
 * Whether a keydown from outside the story should scroll it. With nothing
 * focused the browser scrolls the panel last pressed, so `pressed` (the last
 * mousedown target) stands in for the focus. `spaceTaken` is set while replay
 * answers Space.
 */
export function forwardsScrollKey(event, scroller, { spaceTaken = false, pressed = null } = {}) {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) {
        return false;
    }
    const onBody = isPage(event.target);
    if (BODY_KEYS.includes(event.key)) {
        if (!onBody || (event.key === ' ' && spaceTaken)) {
            return false;
        }
    } else if (!PAGE_KEYS.includes(event.key)) {
        return false;
    }
    const origin = onBody && pressed?.isConnected ? pressed : event.target;
    if (isPage(origin)) {
        return true;
    }
    if (scroller.contains(origin) || origin.closest(TAKES_TEXT) || origin.closest(MENU)) {
        return false;
    }
    for (let el = origin; el && !isPage(el); el = el.parentElement) {
        if (scrollsItself(el)) {
            return false;
        }
    }
    return true;
}

function canScrollToward(el, deltaY) {
    if (!scrollsItself(el)) {
        return false;
    }
    return deltaY < 0 ? el.scrollTop > 0 : el.scrollTop + el.clientHeight < el.scrollHeight - 1;
}

/** Whether a wheel turn outside the story should scroll it. Ctrl+wheel zooms. */
export function forwardsWheel(event, scroller) {
    if (event.defaultPrevented || event.ctrlKey || !event.deltaY) {
        return false;
    }
    const target = event.target;
    if (scroller.contains(target) || target.closest(MENU)) {
        return false;
    }
    for (let el = target; el && !isPage(el); el = el.parentElement) {
        if (canScrollToward(el, event.deltaY)) {
            return false;
        }
    }
    return true;
}

// Where a smooth key scroll is headed while it runs: the next key steps on from
// there, as the browser's own keyboard scrolling does, rather than from where
// the animation has got to. Kept until the scroll ends, and dropped as soon as
// anything else moves the scroller: input on it, or a step away from the target.
const heading = new WeakMap();
const watched = new WeakSet();

// without scrollend nothing says when an animation is over: step at once
function canAnimate() {
    return 'onscrollend' in window && !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

function watch(scroller) {
    if (watched.has(scroller)) {
        return;
    }
    watched.add(scroller);
    const drop = () => heading.delete(scroller);
    scroller.addEventListener('scrollend', drop);
    for (const type of ['wheel', 'pointerdown', 'touchstart']) {
        scroller.addEventListener(type, drop, { passive: true });
    }
    scroller.addEventListener('scroll', () => {
        const run = heading.get(scroller);
        if (!run) {
            return;
        }
        const now = scroller.scrollTop;
        const down = run.top >= run.last;
        const away = down ? now < run.last - 1 || now > run.top + 1 : now > run.last + 1 || now < run.top - 1;
        if (away) {
            heading.delete(scroller);
        } else {
            run.last = now;
        }
    }, { passive: true });
}

function stepTo(scroller, top, behavior) {
    const target = Math.max(0, Math.min(top, scroller.scrollHeight - scroller.clientHeight));
    if (behavior === 'smooth' && target !== scroller.scrollTop) {
        watch(scroller);
        heading.set(scroller, { top: target, last: scroller.scrollTop });
    } else {
        heading.delete(scroller);
    }
    scroller.scrollTo({ top: target, behavior });
}

export function scrollByKey(scroller, event) {
    const page = scroller.clientHeight * PAGE_FRACTION;
    // an auto-repeat steps at once: each would otherwise restart the animation
    const behavior = !event.repeat && canAnimate() ? 'smooth' : 'auto';
    if (event.key === 'Home') {
        stepTo(scroller, 0, behavior);
        return;
    }
    if (event.key === 'End') {
        stepTo(scroller, scroller.scrollHeight, behavior);
        return;
    }
    const step = {
        PageUp: -page,
        PageDown: page,
        ' ': event.shiftKey ? -page : page,
        ArrowUp: -LINE_STEP,
        ArrowDown: LINE_STEP,
    }[event.key];
    const from = heading.get(scroller)?.top ?? scroller.scrollTop;
    stepTo(scroller, from + step, behavior);
}

export function scrollByWheel(scroller, event) {
    const unit = { [WheelEvent.DOM_DELTA_LINE]: LINE_STEP, [WheelEvent.DOM_DELTA_PAGE]: scroller.clientHeight }[event.deltaMode] || 1;
    heading.delete(scroller);
    scroller.scrollBy({ top: event.deltaY * unit });
}
