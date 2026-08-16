// History-chain decisions of the scene timeline: whether the recorded chain can
// still be trusted, what a repair does to what the dialog is browsing, and what
// the backend's timeline answers mean for it. All of it is a decision over the
// state handed in — the dialog owns the state itself and the websocket.

/**
 * Whether the scene's history chain has to be repaired before the timeline can
 * be trusted. A scene with no chain report (an old save, a scene that never
 * recorded one) is not broken — there is simply nothing to verify.
 */
export function chainNeedsRepair(chain) {
    return !!chain && chain.status !== 'ok';
}

/**
 * What to tell the user about a timeline that has been repaired before, or null
 * when it never was. Only the last repair is worth naming: it is the one that
 * cut the revisions now missing from the timeline, and the folder the chain it
 * cut was preserved in.
 */
export function rebaseNote(rebase, formatTimestamp) {
    const rebases = rebase?.rebases;
    if (!rebases?.length) {
        return null;
    }
    const last = rebases[rebases.length - 1];
    return `This timeline was repaired on ${formatTimestamp(last.ts)}. Anything recorded before then is no longer shown — the old history files are kept in the scene's changelog/${last.preserved_to} folder.`;
}

/**
 * Why the scene cannot be rolled back to the selected revision, or null when it
 * can. A broken chain is reported first: the recorded revisions no longer match
 * the state they were made from, so rolling back to one would restore something
 * the timeline is misrepresenting.
 */
export function rollbackDisabledReason({ needsRepair, sceneData }) {
    if (needsRepair) {
        return "The scene's history needs to be repaired before rollback is available.";
    }
    if (sceneData?.immutable_save) {
        return 'This save is immutable and cannot be rolled back in place — fork instead.';
    }
    if (!sceneData?.filename) {
        return 'The scene must be saved before it can be rolled back.';
    }
    return null;
}

/**
 * The browse state a repair starts from. The revision the dialog was asked to
 * open at is forgotten: a repair starts a fresh chain, so the refreshed list
 * carries different revisions and the one that was pinned is gone from it.
 */
export function repairBrowseState() {
    return {
        applying: true,
        applyAction: 'repair',
        loadingRevisions: true,
        initialRev: null,
    };
}

/**
 * What a `revisions` answer makes of the dialog's state, or null when the
 * answer is about a different scene than the one being browsed.
 *
 * `sliderIndex` is where the scrubber lands: the revision the dialog was opened
 * at when it is still on the timeline, the latest one otherwise. `requestPreview`
 * says the preview has to be asked for directly — landing on the index the
 * scrubber already sits on moves nothing, so nothing would ask for it.
 */
export function revisionsUpdate(data, { scenePath, initialRev, sliderIndex }) {
    if ((data.scene_path || null) !== scenePath) {
        return null;
    }
    const revisions = data.revisions || [];
    const update = {
        revisions,
        chain: data.chain || null,
        rebase: data.rebase || null,
        loadingRevisions: false,
        sliderIndex,
        requestPreview: false,
    };
    if (revisions.length === 0) {
        return update;
    }
    let index = revisions.length - 1;
    if (initialRev !== null) {
        const exact = revisions.findIndex((entry) => entry.rev === initialRev);
        if (exact !== -1) {
            index = exact;
        }
    }
    update.sliderIndex = index;
    update.requestPreview = index === sliderIndex;
    return update;
}

/**
 * What an `operation_done` answer means for the dialog:
 *
 *   * `clearLoading`  — the request failed, so nothing is on its way anymore;
 *                       failed list / preview requests land here too;
 *   * `clearApplying` — an operation of ours was what finished;
 *   * `close`         — it succeeded and there is nothing left to look at. A
 *                       repair is the exception: it refreshes the revisions
 *                       list in place, and closing would yank it from under
 *                       the user.
 */
export function operationDoneOutcome(data, { applying, applyAction }) {
    return {
        clearLoading: !!data.error,
        clearApplying: applying,
        close: applying && !data.error && applyAction !== 'repair',
    };
}
