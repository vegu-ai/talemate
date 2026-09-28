export const PROVIDER_NAMES = {
    openrouter: 'OpenRouter',
    systemone: 'SystemOne API',
};

// src/talemate/decisions/provider.py FailureCode
const FAILURE_REASONS = {
    disabled: 'the decision model is off',
    unavailable: 'the setup is not finished',
    invalid_request: 'the request was not valid',
    unsupported: 'the model cannot answer this kind of question',
    oversize: 'the text was too long for the model',
    timeout: 'no answer came within the time limit',
    transport: 'Talemate could not reach the provider',
    authentication: 'the provider did not accept the API key',
    invalid_response: 'the answer could not be read',
    refused: 'the provider refused the request',
    template: 'the policy template could not run',
    result: 'the policy gave no usable result',
    action: 'the action failed',
    action_denied: 'the action is not allowed here',
    budget: 'the action reached its limit',
    fallback: 'the usual request failed as well',
};

const MISSING_SETTINGS = {
    api_key: 'an OpenRouter API key',
    model: 'a model name',
    base_url: 'a server address',
};

export function missingText(missing) {
    const names = missing.map((name) => MISSING_SETTINGS[name]).filter(Boolean);
    if (!names.length) {
        return 'Needs more settings.';
    }
    const list = names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names.at(-1)}` : names[0];
    return `Needs ${list}.`;
}

export function providerName(provider) {
    return PROVIDER_NAMES[provider] || provider || 'No provider';
}

export function failureReason(code) {
    return FAILURE_REASONS[code] || String(code).replace(/_/g, ' ');
}

export function lastFailureText(failure) {
    if (!failure) {
        return null;
    }
    const what = failure.dispatched ? 'failed' : 'was not sent';
    return `The last request ${what}: ${failureReason(failure.code)}.`;
}
