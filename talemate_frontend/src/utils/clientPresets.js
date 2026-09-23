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

