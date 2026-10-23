// What the template editor may take from a `template_saved` echo. The echo is
// broadcast to everything listening and carries no request id, so an editor can
// only tell its own save apart by what the echoed template says.

// fields that identify a template independently of its uid — a saved template
// is stored under its group by name and type
const IDENTITY_FIELDS = ['name', 'template_type', 'group'];

/**
 * The uid an open create form adopts from a `template_saved` echo, or null when
 * the echo is none of its business.
 *
 * A created template only ever learns its uid from the echo: the form sends a
 * uid-less template and the backend mints one. Without the uid the template
 * cannot be installed or edited in place, so the user would have to reselect it
 * in the sidebar. Only an echo carrying the same identity is adopted — a
 * template saved from somewhere else (the scene tool shortcut modal saves one
 * straight from the scene tools menu) must not stamp its uid onto the form.
 */
export function adoptedTemplateUid(local, saved) {
    if (!local || local.uid || !saved || !saved.uid) {
        return null;
    }
    if (!IDENTITY_FIELDS.every(field => saved[field] === local[field])) {
        return null;
    }
    return saved.uid;
}
