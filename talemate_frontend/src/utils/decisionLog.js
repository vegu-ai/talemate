import { reactive } from "vue";
import { failureReason } from "./decisionModelText";

// The backend owns retention and clearing, so this store only applies its frames.
export function createDecisionLog() {
    return reactive({ requests: {}, invocations: {}, seen: {}, total: 0 });
}

export const decisionLog = createDecisionLog();

// src/talemate/decisions/policy.py writes this when the template supplied no reason
const UNSPECIFIED = "reason unspecified";

/**
 * A row is one retained backend entry. An invocation earns one only once it has
 * finished without making a request, which is the backend's own retention unit.
 */
function isRow(collection, entry) {
    if (collection === "requests") return true;
    return !entry.request_count && !["new", "running"].includes(entry.status);
}

function store(state, collection, entry) {
    if (isRow(collection, entry) && !(entry.id in state.seen)) {
        state.seen[entry.id] = ++state.total;
    }
    state[collection][entry.id] = entry;
}

function oldestFirst(first, second) {
    return first[1].timestamp < second[1].timestamp ? -1 : 1;
}

export function applyDecisionFrame(state, frame) {
    if (frame.event === "snapshot") {
        const entries = [
            ...frame.invocations.map(entry => ["invocations", entry]),
            ...frame.requests.map(entry => ["requests", entry]),
        ];
        const present = new Set(entries.map(([, entry]) => entry.id));
        for (const id of Object.keys(state.seen)) {
            if (!present.has(id)) delete state.seen[id];
        }
        state.requests = {};
        state.invocations = {};
        for (const [collection, entry] of entries.sort(oldestFirst)) {
            store(state, collection, entry);
        }
    } else if (frame.event === "request") {
        store(state, "requests", frame.entry);
    } else if (frame.event === "invocation") {
        store(state, "invocations", frame.entry);
    } else if (frame.event === "removed") {
        for (const id of frame.request_ids) {
            delete state.requests[id];
            delete state.seen[id];
        }
        for (const id of frame.invocation_ids) {
            delete state.invocations[id];
            delete state.seen[id];
        }
    }
}

/**
 * Per invocation: the action ids its requests claim, and how many of its requests the
 * log still holds. `request_count` never decreases, so a smaller number of held
 * requests means retention took one and its actions have no knowable owner.
 */
function noRequests() {
    return { claimed: new Set(), retained: 0 };
}

function requestsPerInvocation(state) {
    const held = {};
    for (const request of Object.values(state.requests)) {
        const entry = held[request.invocation_id]
            || (held[request.invocation_id] = noRequests());
        entry.retained += 1;
        for (const action of request.actions) entry.claimed.add(action.id);
    }
    return held;
}

export function decisionRows(state) {
    const held = requestsPerInvocation(state);
    const rows = Object.values(state.requests).map(request => ({
        id: request.id,
        request,
        invocation: state.invocations[request.invocation_id] || null,
    }));
    for (const invocation of Object.values(state.invocations)) {
        if (isRow("invocations", invocation)) {
            rows.push({ id: invocation.id, request: null, invocation });
        }
    }
    return rows
        .map(row => {
            const actions = rowActions(row, held[row.invocation?.id] || noRequests());
            const status = decisionRowStatus(row, actions);
            return {
                ...row,
                actions,
                status,
                num: state.seen[row.id],
                timestamp: (row.request || row.invocation).timestamp,
            };
        })
        .sort(newestFirst);
}

function newestFirst(first, second) {
    if (first.timestamp !== second.timestamp) return first.timestamp < second.timestamp ? 1 : -1;
    return second.num - first.num;
}

function formatProbability(value) {
    return value.toFixed(2);
}

function formatDetail(value) {
    if (isNumericMap(value)) return [...new Set(Object.values(value))]
        .sort((first, second) => first - second).map(formatDetail).join(", ");
    if (typeof value !== "number") return String(value);
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function isSimple(value) {
    return ["number", "string", "boolean"].includes(typeof value);
}

function isNumericMap(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value)
        && Object.values(value).length > 0
        && Object.values(value).every(item => typeof item === "number" && Number.isFinite(item));
}

function words(token) {
    return token.replace(/_/g, " ");
}

export function questionName(id) {
    return words(id);
}

function sentence(text) {
    return text.charAt(0).toUpperCase() + text.slice(1);
}

// display names for the policies Talemate ships, by template uid; an edited
// policy keeps its uid, and any other policy is named from its own label
const FEATURES = {
    "editor.decision-checks": "Editor checks",
    "world_state.decision-pin-conditions": "Context pin conditions",
    "world_state.decision-avatar": "Portrait selection",
    "world_state.decision-query": "Yes/no question",
    "world_state.decision-reinforcement": "Tracked state update",
    "world_state.decision-snapshot-references": "Characters mentioned (World State)",
    "memory.decision-entity-references": "Characters mentioned (Memory)",
};

export function decisionFeature(row) {
    const entry = row.request || row.invocation;
    if (FEATURES[entry.template_uid]) return FEATURES[entry.template_uid];
    const name = row.request?.label || entry.template_uid.split(".").at(-1).replace(/^decision-/, "");
    return sentence(words(name).replace(/-/g, " "));
}

export function answerValue(answer) {
    if (answer.type === "noul") return `probability ${formatProbability(answer.p_true)}`;
    if (answer.type === "choice") return String(answer.selected);
    return `${formatProbability(answer.value)} of ${answer.legend.length - 1}`;
}

export function answerSummary(id, answer) {
    return `${words(id)} · ${answerValue(answer)}`;
}

export function questionGroups(request) {
    const groups = new Map();
    const flaggedIds = request?.outcomes.findLast(outcome =>
        Array.isArray(outcome.details?.flagged_question_ids))?.details.flagged_question_ids;
    for (const [id, question] of Object.entries(request?.questions || {})) {
        const presentation = request.presentation[id];
        const key = presentation ? `group:${presentation.group_id}` : `question:${id}`;
        if (!groups.has(key)) {
            groups.set(key, {
                id: key,
                label: presentation?.label || words(id),
                instructions: presentation?.instructions || question.instructions,
                questions: [],
            });
        }
        const answer = request.answers?.[id];
        groups.get(key).questions.push({
            id, question, answer, presentation,
            flagged: presentation && answer && flaggedIds ? flaggedIds.includes(id) : null,
        });
    }
    return [...groups.values()];
}

export function decisionProbability(value) {
    const rounded = value.toFixed(2);
    return Number(rounded) === value ? rounded : String(value);
}

export function decisionTime(timestamp) {
    return new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function decisionResult(row) {
    const questions = questionGroups(row.request).flatMap(group => group.questions);
    const scored = questions.filter(item => item.presentation && item.answer?.type === 'noul');
    const flagged = scored.filter(item => item.flagged);
    const strongest = [...(flagged.length ? flagged : scored)]
        .sort((a, b) => b.answer.p_true - a.answer.p_true)[0];
    if (strongest) {
        const { presentation, answer } = strongest;
        const score = `${presentation.passage_id} · ${decisionProbability(answer.p_true)} (threshold ${decisionProbability(presentation.threshold)})`;
        if (flagged.length) {
            return `Flagged ${score}` + (flagged.length > 1 ? ` · ${flagged.length - 1} more flagged` : '');
        }
        const verdict = scored.some(item => item.flagged === false);
        return `${verdict ? 'Nothing flagged · highest' : 'Highest'} ${score}`;
    }
    const failure = row.request?.failure || row.request?.policy_failure;
    if (failure) return sentence(failureReason(failure.code));
    if (questions.length === 1 && questions[0].answer) return answerSummary(questions[0].id, questions[0].answer);
    if (questions.length) return `${questions.length} question${questions.length === 1 ? '' : 's'}${row.request?.status === 'pending' ? ' · waiting for the answer' : ''}`;
    return 'No questions submitted';
}

export function decisionOutcome(row) {
    if (row.status === 'active') return { label: 'In progress', color: 'primary', icon: 'mdi-progress-clock' };
    if (row.status === 'failed') return { label: row.request?.dispatched === false ? 'Not sent' : 'Failed', color: 'error', icon: 'mdi-alert-circle-outline' };
    if (row.status === 'cancelled') return { label: 'Cancelled', color: 'muted', icon: 'mdi-cancel' };
    const actions = row.actions.filter(action => !action.unassociated);
    const lastAction = actions.at(-1);
    if (lastAction) return {
        label: `${actionName(lastAction.action)} ${lastAction.status}`,
        color: lastAction.status === 'completed' ? 'success' : 'muted', icon: 'mdi-check-circle-outline',
    };
    const outcome = row.request?.outcomes.at(-1);
    return { label: outcome ? sentence(words(outcome.action)) : 'No action', color: 'muted', icon: 'mdi-minus-circle-outline' };
}

/**
 * A reason token ending in `_<detail name>` reads that detail's value in place of
 * the suffix, so `below_threshold` with `threshold=0.8` becomes `below 0.80`. Any
 * other reason is shown as the template wrote it, with its details appended.
 */
function spokenReason(reason, details) {
    const suffix = Object.keys(details)
        .filter(key => isSimple(details[key]) || isNumericMap(details[key]))
        .filter(key => reason.endsWith(`_${key}`) && reason.length > key.length + 1)
        .sort((first, second) => second.length - first.length)[0];
    if (!suffix) return { text: words(reason), used: null };
    const head = words(reason.slice(0, -(suffix.length + 1)));
    const name = isNumericMap(details[suffix]) ? `${words(suffix)} ` : "";
    return { text: `${head} ${name}${formatDetail(details[suffix])}`, used: suffix };
}

export function outcomeSummary(outcome) {
    const label = sentence(words(outcome.action));
    if (outcome.reason === UNSPECIFIED) return `${label}; ${UNSPECIFIED}`;
    const details = outcome.details || {};
    const { text, used } = spokenReason(outcome.reason, details);
    const rest = Object.entries(details)
        .filter(([key, value]) => key !== used && (isSimple(value) || isNumericMap(value)))
        .map(([key, value]) => `${words(key)}=${formatDetail(value)}`);
    return `${label} (${[text, ...rest].join(", ")})`;
}

// the agent prefix is left to the technical details, which keep the full action name
function actionName(action) {
    return sentence(words(action.split(".").at(-1)));
}

export function actionSummary(action) {
    const note = action.failure ? action.failure.code : action.reason;
    return [
        `${actionName(action.action)} ${action.status}`,
        note ? `(${words(note)})` : null,
        action.elapsed_ms == null ? null : `· ${Math.round(action.elapsed_ms)} ms`,
    ].filter(Boolean).join(" ");
}

/**
 * This row's own actions, then the ones no request of the invocation claimed. An
 * action a sibling request named belongs to that row, not to this one, and once
 * retention has taken a sibling the rest of the trace makes no claim either way.
 */
function rowActions(row, held) {
    const own = row.request ? row.request.actions : row.invocation.actions;
    const whole = row.invocation && held.retained >= row.invocation.request_count;
    const trace = row.request && whole ? row.invocation.actions : [];
    return [
        ...own,
        ...trace
            .filter(action => !held.claimed.has(action.id))
            .map(action => ({ ...action, unassociated: true })),
    ];
}

function decisionRowStatus(row, actions) {
    const { request, invocation } = row;
    const own = actions.filter(action => !action.unassociated);
    if (request?.status === "pending") return "active";
    if (own.some(action => action.status === "pending")) return "active";
    if (invocation && ["new", "running"].includes(invocation.status)) return "active";
    if (request?.status === "failed" || request?.policy_failure) return "failed";
    if (own.some(action => action.status === "failed")) return "failed";
    if (request?.status === "cancelled" || invocation?.status === "cancelled") return "cancelled";
    if (own.some(action => action.status === "cancelled")) return "cancelled";
    return "completed";
}
