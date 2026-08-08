// Shared helpers for seeding a new client from its type metadata.
//
// Used by the Connections > Clients page and the onboarding wizard, which both
// create clients from the `client_types` message and must produce the same
// shape.

export function clientNamePrefix(meta, type) {
    return meta?.name_prefix || meta?.title || type;
}

export function uniqueClientName(prefix, takenNames) {
    const taken = new Set(takenNames || []);
    let name = prefix;
    let i = 2;
    while (taken.has(name)) {
        name = `${prefix} ${i}`;
        i++;
    }
    return name;
}

// Seed a new client from its type's `Meta().defaults` and let the backend
// model supply everything else.
//
// Fields the defaults don't carry must be OMITTED, never nulled: client types
// declare extra fields on their config model that `Defaults` doesn't include
// (openrouter's `concurrent_inference_enabled`, typed `bool`, is the common
// one), and a null there fails validation for the whole config, so the save is
// refused with no way forward.
export function buildClientFromDefaults(meta, type, takenNames) {
    return {
        ...(meta?.defaults || {}),
        type: type,
        name: uniqueClientName(clientNamePrefix(meta, type), takenNames),
        enabled: true,
    };
}

// Defaults the backend client model (`config.schema.Client`) applies to fields
// `Meta.defaults` does not carry. Display only: a new client is seeded by
// omission (above) and the model fills these in on save, so the editor needs
// them to show the effective value before the first round-trip.
export const CLIENT_MODEL_DEFAULTS = {
    reason_failure_behavior: 'fail',
    enforce_response_length: 'adaptive',
    optimize_prompt_caching: false,
    dedupe_enabled: false,
};

// Step sizes for the context-length slider. Shared by the client editor and
// the drawer's inline slider so the two surfaces snap to the same values.
export const TOKEN_GRADUATIONS = [
    { from: 0, step: 64 },
    { from: 1024, step: 256 },
    { from: 4096, step: 512 },
    { from: 8192, step: 1024 },
    { from: 65536, step: 2048 },
];
