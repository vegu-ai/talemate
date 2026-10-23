const STEP_PROGRESS = { analysis: 'Analyzing', tags: 'Tagging', reference: 'Marking' };
const STEP_NAME = { analysis: 'Analysis', tags: 'Tagging', reference: 'Marking' };
const UNTYPED = 'Give the image a type in the Visual Library first';

// how long a clean finish keeps its marker on a message image
export const REFERENCE_DONE_MS = 3000;

/**
 * The generation types an image of `visType` is marked for, from the
 * visual agent's status (REFERENCE_TARGETS in
 * src/talemate/agents/visual/reference.py).
 */
export function referenceTargets(visualMeta, visType) {
    return visualMeta?.reference_targets?.[visType] || [];
}

export function isReferenceCandidate(meta, targets) {
    const reference = meta?.reference || [];
    return targets.length > 0 && targets.every((visType) => reference.includes(visType));
}

function targetsLabel(targets) {
    const names = targets.map((visType) => `${visType.toLowerCase().replace(/_/g, ' ')}s`);
    return names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names.join('');
}

function errorSummary(errors) {
    return errors.map((error) => `${STEP_NAME[error.step] || error.step} failed: ${error.message.replace(/\.?$/, '.')}`).join(' ');
}

/**
 * What the "Mark as reference" control shows for an image, from its asset
 * meta, the generation types its type is marked for, and the latest
 * mark_as_reference_progress frame for it (if any). A finished frame counts
 * as marked until the next scene status brings the asset meta it wrote
 * (`settled`).
 */
export function referenceState(meta, progress, targets) {
    if (progress && !progress.finished) {
        const label = STEP_PROGRESS[progress.step] || 'Starting';
        return { status: 'running', label: `${label}…`, tooltip: 'Preparing this image as a reference' };
    }
    if (!targets.length) {
        return { status: 'unavailable', tooltip: UNTYPED };
    }
    const errors = progress?.errors || [];
    const marked = isReferenceCandidate(meta, targets) || (!!progress?.marked && !progress.settled);
    if (marked) {
        const label = `Marked as a reference for ${targetsLabel(targets)}`;
        return { status: 'marked', warning: errors.length > 0, tooltip: errors.length ? `${label}. ${errorSummary(errors)}` : label };
    }
    if (errors.length && !progress.marked) {
        return { status: 'failed', tooltip: `${errorSummary(errors)} Click to try again.` };
    }
    return {
        status: 'idle',
        tooltip: `Mark as reference: analyze and tag this image so ${targetsLabel(targets)} can use it`,
    };
}

/**
 * Whether a message image shows the status of a run started from its menu:
 * while it runs, when it failed or marked with a step error, and for
 * REFERENCE_DONE_MS after a clean finish (until `quiet`). Never idle.
 */
export function referenceStatusVisible(state, progress) {
    if (!progress) return false;
    if (state.status === 'running' || state.status === 'failed') return true;
    return state.status === 'marked' && (state.warning || !progress.quiet);
}
