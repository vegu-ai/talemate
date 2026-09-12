export const KNOWLEDGE_CHANGE_LIFETIME = 8000;

export function createKnowledgeChanges(publish) {
    const characters = new Map();
    const update = () => publish(new Map(
        [...characters].map(([name, entry]) => [name, [...entry.changes.values()]])));
    const schedule = (name, entry) => {
        clearTimeout(entry.timer);
        if (entry.pauses.size) return;
        entry.started = Date.now();
        entry.timer = setTimeout(() => {
            characters.delete(name);
            update();
        }, entry.remaining);
    };
    return {
        add(changes, names) {
            const known = new Set(names);
            for (const change of changes) {
                if (!known.has(change.character)) continue;
                let entry = characters.get(change.character);
                if (!entry) {
                    entry = { changes: new Map(), pauses: new Set(), timer: null };
                    characters.set(change.character, entry);
                }
                entry.changes.set(JSON.stringify([change.target, change.kind]), change);
                entry.remaining = KNOWLEDGE_CHANGE_LIFETIME;
                schedule(change.character, entry);
            }
            update();
        },
        pause(name, reason, paused) {
            const entry = characters.get(name);
            if (!entry) return;
            if (paused) {
                if (!entry.pauses.size) {
                    entry.remaining = Math.max(0, entry.remaining - (Date.now() - entry.started));
                    clearTimeout(entry.timer);
                }
                entry.pauses.add(reason);
            } else {
                if (!entry.pauses.has(reason)) return;
                entry.pauses.delete(reason);
                if (!entry.pauses.size) schedule(name, entry);
            }
        },
        clear() {
            for (const entry of characters.values()) clearTimeout(entry.timer);
            characters.clear();
            update();
        },
    };
}
