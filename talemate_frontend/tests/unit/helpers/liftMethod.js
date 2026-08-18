// The suite runs in a node environment with no vue plugin, so components cannot
// be mounted - lift a method or computed body out of the .vue source and run it
// against stubs, so a spec pins the component's own code rather than a copy of
// it. Failures here are loud by design: a body that cannot be located or is not
// brace balanced fails the expectation rather than silently lifting nothing.
import { readFileSync } from "node:fs";
import { expect } from "vitest";

export function readSource(path) {
    return readFileSync(path, "utf-8");
}

export function methodSource(source, name, label) {
    const declaration = new RegExp(`(?:^|[^\\w.$])${name}\\(([^)]*)\\) \\{`);
    const match = declaration.exec(source);
    expect(match, `${label} has no ${name}() method`).not.toBeNull();

    const start = source.indexOf("{", match.index + match[0].length - 1);
    let depth = 0;
    let end = -1;
    for (let i = start; i < source.length; i++) {
        if (source[i] === "{") depth++;
        if (source[i] === "}") depth--;
        if (depth === 0) {
            end = i;
            break;
        }
    }
    expect(end, `${name}() in ${label} is not brace balanced`).toBeGreaterThan(-1);

    const body = source.slice(start + 1, end);
    expect(body.trim().length, `${name}() in ${label} lifted an empty body`).toBeGreaterThan(0);
    return { params: match[1], body };
}

export function lift(source, name, label, deps = {}) {
    const { params, body } = methodSource(source, name, label);
    const names = Object.keys(deps);
    const factory = new Function(...names, `return function (${params}) {${body}};`);
    return factory(...names.map((dep) => deps[dep]));
}

// Reads a module-level array or object literal (e.g. a component's local
// constant) so a spec can run a lifted body against the component's real data.
export function constant(source, name, label) {
    const match = new RegExp(`const ${name} = ([[{][\\s\\S]*?\\n[\\]}]);`).exec(source);
    expect(match, `${label} has no ${name} list`).not.toBeNull();
    return new Function(`return ${match[1]};`)();
}
