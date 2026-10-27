const ARG_INPUTS = {
    bool: 'checkbox',
    int: 'number',
    float: 'number',
    list: 'textarea',
};

export function menuCommands(commands) {
    return (commands || []).filter(command => !!command.menu);
}

export function groupByMenu(commands) {
    const groups = new Map();

    for (const command of menuCommands(commands)) {
        if (!groups.has(command.menu)) {
            groups.set(command.menu, []);
        }
        groups.get(command.menu).push(command);
    }

    return [...groups.keys()]
        .sort((a, b) => a.localeCompare(b))
        .map(menu => ({ menu, commands: groups.get(menu) }));
}

export function argFields(command) {
    return ((command && command.args) || []).map(arg => ({
        name: arg.name,
        typ: arg.typ,
        input: ARG_INPUTS[arg.typ] || 'text',
    }));
}

export function buildArgs(fields, values) {
    const args = {};

    for (const field of fields || []) {
        const value = (values || {})[field.name];
        // an argument left blank is omitted entirely so the command module's
        // own default applies - Number('') would send a 0 instead
        if (value === undefined || value === null || value === '') {
            continue;
        }
        args[field.name] = field.input === 'number' ? Number(value) : value;
    }

    return args;
}
