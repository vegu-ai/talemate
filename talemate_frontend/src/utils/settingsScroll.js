const GAP = 8;

// Targets scroll in below the app bar and the pinned toolbar, whatever
// height the toolbar has now; one taller than the visible area aligns its
// top edge, since centering would cut that edge off under the toolbar.
export function scrollSettingIntoView(el) {
    const pin = document.querySelector('.app-settings-toolbar-pin');
    const margin = pin ? (parseFloat(getComputedStyle(pin).top) || 0) + pin.offsetHeight + GAP : 0;
    el.style.scrollMarginTop = `${margin}px`;
    const fits = el.offsetHeight + margin * 2 <= window.innerHeight;
    el.scrollIntoView({ behavior: 'smooth', block: fits ? 'center' : 'start' });
}
