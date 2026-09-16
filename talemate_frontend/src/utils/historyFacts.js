import { effectiveConfigValue } from '@/constants/sceneAgentSettings';

export const EXTRACT_FACTS_OFF_HINT =
    'Extract facts is off. Turn on Summarizer › Summarization › Extract facts to generate facts.';

/** The entry has facts, or facts were already extracted from it. */
export function hasFactRecord(entry) {
    return !!(entry?.facts_status || entry?.facts?.length);
}

export function needsFacts(entry) {
    return entry?.layer === 0
        && !!entry.id
        && !hasFactRecord(entry)
        && !entry.facts_unavailable_reason;
}

/**
 * The Summarizer's Extract facts setting as the loaded scene sees it, from the
 * live agent status. Null while that status has not arrived.
 */
export function extractFactsEnabled(agents) {
    const summarizer = (agents || []).find((agent) => agent.name === 'summarizer');
    if (!summarizer?.actions?.archive?.config?.extract_facts) return null;
    return !!effectiveConfigValue(
        summarizer.actions,
        summarizer.data?.scene_overrides || {},
        'archive.config.extract_facts',
    );
}

/** One line on how a Generate missing facts run ended. */
export function missingFactsSummary(result) {
    if (!result) return '';
    // a refused request never started a run
    if (result.total === undefined) return result.error || '';
    const parts = [];
    if (result.stopped || result.error) {
        parts.push(`Stopped after ${result.done} of ${result.total} ${result.total === 1 ? 'entry' : 'entries'}.`);
    }
    parts.push(`Facts generated for ${result.ok} ${result.ok === 1 ? 'entry' : 'entries'}.`);
    if (result.failed) {
        parts.push(`${result.failed} failed and ${result.failed === 1 ? 'is' : 'are'} marked facts failed.`);
    }
    if (result.error) parts.push(`Error: ${result.error}`);
    return parts.join(' ');
}
