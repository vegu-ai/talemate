export const PAGE_SIZE = 50;

export const DEFAULT_FILTERS = Object.freeze({ span: 1, since: '', until: '', search: '' });

/** A response belongs to one opening and selection, including repeated clicks. */
export function matchesPreview(data, scenePath, rev, requestId) {
    return data.request_id === requestId && data.rev === rev
        && (data.scene_path || null) === scenePath;
}

export function previewFailureText(code) {
    if (code === 'damaged_blob') return 'Some saved content is missing or damaged.';
    return 'The saved state could not be read.';
}

/** A datetime-local input value as epoch seconds. */
export function toTimestamp(value, { endOfMinute = false } = {}) {
    if (!value) return null;
    const ms = new Date(value).getTime();
    if (Number.isNaN(ms)) return null;
    return Math.floor(ms / 1000) + (endOfMinute ? 59 : 0);
}

export function filtersActive(filters) {
    return filters.span !== DEFAULT_FILTERS.span || !!filters.since || !!filters.until || !!filters.search?.trim();
}

export function revisionQuery(filters, { beforeRev = null, includeRev = null } = {}) {
    return {
        span: Number.isInteger(filters.span) && filters.span >= 1 ? filters.span : 1,
        limit: PAGE_SIZE,
        before_rev: beforeRev,
        since_ts: toTimestamp(filters.since),
        until_ts: toTimestamp(filters.until, { endOfMinute: true }),
        search: filters.search?.trim() || '',
        include_rev: includeRev,
    };
}

/** The loaded revision to select: the requested one, else the newest loaded. */
export function pickRevision(groups, wantedRev) {
    const revisions = groups.flatMap(group => group.revisions);
    return revisions.find(entry => entry.rev === wantedRev)?.rev ?? revisions[0]?.rev ?? null;
}
