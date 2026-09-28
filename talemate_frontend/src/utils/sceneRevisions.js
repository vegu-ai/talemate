/** Select the requested saved state, falling back to the latest revision. */
export function revisionIndex(revisions, initialRev) {
    const index = revisions.findIndex(entry => entry.rev === initialRev);
    return index >= 0 ? index : Math.max(0, revisions.length - 1);
}

/** A response belongs to one opening and selection, including repeated clicks. */
export function matchesPreview(data, scenePath, rev, requestId) {
    return data.request_id === requestId && data.rev === rev
        && (data.scene_path || null) === scenePath;
}

export function previewFailureText(code) {
    if (code === 'damaged_blob') return 'Some saved content is missing or damaged.';
    return 'The saved state could not be read.';
}
