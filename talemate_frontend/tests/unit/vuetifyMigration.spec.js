import { readdirSync, readFileSync } from "node:fs";
import { extname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const DEFAULT_SRC_ROOT = fileURLToPath(new URL("../../src", import.meta.url));
const SRC_ROOT = process.env.VUETIFY_MIGRATION_SOURCE_ROOT
  ? resolve(process.env.VUETIFY_MIGRATION_SOURCE_ROOT)
  : DEFAULT_SRC_ROOT;
const VUETIFY_CSS = fileURLToPath(
  new URL("../../node_modules/vuetify/dist/vuetify.css", import.meta.url),
);
const RUNTIME_TEXT_CLASS_BASELINE = JSON.parse(
  readFileSync(
    fileURLToPath(
      new URL("./fixtures/vuetifyRuntimeTextClasses.json", import.meta.url),
    ),
    "utf8",
  ),
);
const SOURCE_EXTENSIONS = new Set([".css", ".js", ".mjs", ".vue"]);

function sourceFiles(directory = SRC_ROOT) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    if (!SOURCE_EXTENSIONS.has(extname(entry.name))) return [];
    return [{ path, source: readFileSync(path, "utf8") }];
  });
}

function definedTextClasses(stylesheet) {
  return new Set(
    [...stylesheet.matchAll(/\.(text-[a-zA-Z0-9_-]+)(?=\s|,|\{|\.|:|#|>|\+|~|\[)/g)].map(
      (match) => match[1],
    ),
  );
}

function usedTextClasses(source) {
  const uses = [];
  for (const attribute of source.matchAll(/\bclass\s*=\s*(["'])([\s\S]*?)\1/g)) {
    const value = attribute[2];
    const valueOffset = attribute.index + attribute[0].indexOf(value);
    for (const token of value.matchAll(
      /(^|[^a-zA-Z0-9_-])(text-[a-zA-Z0-9_-]+)(?![a-zA-Z0-9_-])/g,
    )) {
      uses.push({ token: token[2], index: valueOffset + token.index + token[1].length });
    }
  }
  return uses;
}

function lineNumber(source, index) {
  return source.slice(0, index).split("\n").length;
}

function finding(file, source, index, detail) {
  return `${relative(SRC_ROOT, file)}:${lineNumber(source, index)}: ${detail}`;
}

function expectNoFindings(findings) {
  expect(findings, `${findings.length} finding(s)\n${findings.join("\n")}`).toEqual([]);
}

function componentTags(source, componentPattern) {
  const tagPattern = new RegExp(
    `<${componentPattern}\\b(?:[^"'<>]|"[^"]*"|'[^']*')*>`,
    "gs",
  );
  return [...source.matchAll(tagPattern)];
}

function migratedPropMatches(source) {
  const gridProp =
    /\s(?:v-bind:|:)?dense(?=\s|=|>)|\s(?:v-bind:|:)?(?:align|justify|align-content|order|align-self)(?:-[a-z]+)?=/;
  const snackbarProp = /\s(?:v-bind:|:)?multi-line(?=\s|=|>)/;

  return [
    ...componentTags(source, "v-(?:row|col)").filter((match) =>
      gridProp.test(match[0]),
    ),
    ...componentTags(source, "v-snackbar").filter((match) =>
      snackbarProp.test(match[0]),
    ),
  ];
}

const sources = sourceFiles();

describe("Vuetify 4 source compatibility", () => {
  it("uses text classes defined by CSS or the runtime theme baseline", () => {
    const definedClasses = definedTextClasses(readFileSync(VUETIFY_CSS, "utf8"));
    const baseline = new Set(RUNTIME_TEXT_CLASS_BASELINE);
    const unruledUses = sources.flatMap(({ path, source }) => {
      const locallyDefinedClasses = definedTextClasses(source);
      return usedTextClasses(source)
        .filter(
          ({ token }) =>
            !definedClasses.has(token) && !locallyDefinedClasses.has(token),
        )
        .map(({ token, index }) => ({ path, source, token, index }));
    });
    const actualUnruledClasses = new Set(unruledUses.map(({ token }) => token));
    const findings = unruledUses
      .filter(({ token }) => !baseline.has(token))
      .map(({ path, source, token, index }) =>
        finding(path, source, index, `${token} has no CSS rule`),
      );
    for (const token of baseline) {
      if (!actualUnruledClasses.has(token)) {
        findings.push(
          `runtime baseline: ${token} is not used without a CSS rule; delete the entry from tests/unit/fixtures/vuetifyRuntimeTextClasses.json`,
        );
      }
    }

    expectNoFindings(findings);
  });

  it("does not use migrated Vuetify props", () => {
    const findings = sources.flatMap(({ path, source }) =>
      migratedPropMatches(source).map((match) =>
        finding(path, source, match.index, match[0]),
      ),
    );

    expectNoFindings(findings);
  });

  it("reports undefined text classes and migrated props in inline fixtures", () => {
    const stylesheet = ".text-body-small { font-size: 0.875rem; }";
    const source = `
      <div class="text-body-small text-body-smal text-h6"></div>
      <v-row dense></v-row>
      <v-row :class="count > 3 ? 'wide' : 'narrow'" dense></v-row>
      <v-snackbar multi-line></v-snackbar>
      <v-snackbar :timeout="count > 5 ? 1000 : 2000" multi-line></v-snackbar>
    `;
    const definedClasses = definedTextClasses(stylesheet);
    const undefinedClasses = usedTextClasses(source)
      .filter(({ token }) => !definedClasses.has(token))
      .map(({ token }) => token);
    const propMatches = migratedPropMatches(source).map((match) => match[0]);

    expect(undefinedClasses).toEqual(["text-body-smal", "text-h6"]);
    expect(undefinedClasses).not.toContain("text-body-small");
    expect(propMatches).toEqual([
      "<v-row dense>",
      `<v-row :class="count > 3 ? 'wide' : 'narrow'" dense>`,
      "<v-snackbar multi-line>",
      '<v-snackbar :timeout="count > 5 ? 1000 : 2000" multi-line>',
    ]);
  });
});
