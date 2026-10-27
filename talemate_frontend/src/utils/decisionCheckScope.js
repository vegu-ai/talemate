export const DECISION_CHECK_SCOPES = [
    { value: 'all', title: 'All text', icon: 'mdi-text-box-outline', part: 'text' },
    { value: 'dialogue', title: 'Dialogue only', icon: 'mdi-comment-quote-outline', part: 'dialogue' },
    { value: 'prose', title: 'Prose only', icon: 'mdi-text-long', part: 'prose' },
];

export function decisionCheckScope(value) {
    return DECISION_CHECK_SCOPES.find(scope => scope.value === value) || DECISION_CHECK_SCOPES[0];
}
