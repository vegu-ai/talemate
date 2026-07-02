import { marked, Marked } from 'marked';
import { DEFAULT_APPEARANCE_COLORS } from './messageColors.js';

const DEFAULTS = {
    quotes: {
        color: DEFAULT_APPEARANCE_COLORS.quotes,
        italic: false,
        bold: false,
    },
    parentheses: {
        color: DEFAULT_APPEARANCE_COLORS.parentheses,
        italic: false,
        bold: false,
    },
    brackets: {
        color: DEFAULT_APPEARANCE_COLORS.brackets,
        italic: false,
        bold: true,
    },
    emphasis: {
        color: DEFAULT_APPEARANCE_COLORS.emphasis,
        italic: false,
        bold: false,
    },
    entities: {
        color: DEFAULT_APPEARANCE_COLORS.entities,
        italic: false,
        bold: false,
    },
    default: {
        color: DEFAULT_APPEARANCE_COLORS.emphasis,
        italic: true,
        bold: false,
    },
    prefix: {
        color: "#FFE082",
        italic: false,
        bold: true,
    },
}

// Escape a string for use inside a regex literal.
function escapeRegex(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Escape a string for safe embedding inside an HTML attribute value.
function escapeHtmlAttr(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

// Escape a string for safe embedding as HTML text content.
function escapeHtmlText(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

// Compile an entity-mentions list into the lookup structures used by the
// scene-entity tokenizer extension. Returns null when the list is empty.
//
// mentions: [{ name, kind, phrases: [string, ...] }, ...]
//
// Returned object:
//   - startRegex: matches the first phrase occurrence anywhere in `src`
//   - matchRegex: matches a phrase only at the start of `src`
//   - phraseToEntity: lowercase-phrase → { name, kind }
function compileEntityMentions(mentions) {
    if (!mentions || mentions.length === 0) return null;

    const flat = [];
    const seen = new Set();
    for (const entity of mentions) {
        if (!entity || !Array.isArray(entity.phrases)) continue;
        for (const rawPhrase of entity.phrases) {
            if (typeof rawPhrase !== 'string') continue;
            const phrase = rawPhrase.trim();
            if (!phrase) continue;
            const key = phrase.toLowerCase();
            if (seen.has(key)) continue;
            seen.add(key);
            flat.push({ phrase, key, entity });
        }
    }
    if (flat.length === 0) return null;

    // Longer phrases first so "blast door" wins over "door".
    flat.sort((a, b) => b.phrase.length - a.phrase.length);

    const alternatives = flat
        .map(({ phrase }) => {
            const escaped = escapeRegex(phrase);
            const leading = /^\w/.test(phrase) ? '\\b' : '';
            const trailing = /\w$/.test(phrase) ? '\\b' : '';
            return `${leading}${escaped}${trailing}`;
        })
        .join('|');

    const phraseToEntity = {};
    for (const { key, entity } of flat) {
        phraseToEntity[key] = { name: entity.name, kind: entity.kind };
    }

    return {
        startRegex: new RegExp(`(?:${alternatives})`, 'i'),
        matchRegex: new RegExp(`^(?:${alternatives})`, 'i'),
        phraseToEntity,
    };
}

export class SceneTextParser {
    constructor(config = {}) {
        // Determine default color:
        // 1. Use config.defaultColor if explicitly provided
        // 2. Use message type default from DEFAULT_APPEARANCE_COLORS if messageType is specified
        // 3. Otherwise use DEFAULTS.default.color
        const defaultColor = config.defaultColor ??
                            (config.messageType && DEFAULT_APPEARANCE_COLORS[config.messageType]) ??
                            DEFAULTS.default.color;
        
        // Get the default message color from config.default if available
        const defaultMessageColor = config.default?.color ?? defaultColor;
        
        // Helper to merge a user-supplied style object with defaults
        const merge = (key, defaultObj, defaults, isMarkupStyle = false) => {
            const user = config[key] ?? {};
            let color;

            if (isMarkupStyle && user.override_color === false) {
                // When override_color is false, use the default message color
                color = defaultMessageColor;
            } else {
                // Use the markup's own color if provided, otherwise use defaults
                color = user.color != null ? user.color : defaults.color;
            }

            return {
                className: defaultObj.className,
                style: user.style ?? '',
                color: color,
                bold: user.bold != null ? user.bold : (defaults.bold ?? false),
                italic: user.italic != null ? user.italic : (defaults.italic ?? false),
                show: user.show != null ? user.show : true,
            };
        };
        
        this.config = {
            quotes: merge('quotes', { className: 'scene-quotes' }, { color: DEFAULTS.quotes.color, bold: DEFAULTS.quotes.bold, italic: DEFAULTS.quotes.italic }, true),
            emphasis: merge('emphasis', { className: 'scene-emphasis' }, { color: DEFAULTS.emphasis.color, bold: DEFAULTS.emphasis.bold, italic: DEFAULTS.emphasis.italic }, true),
            parentheses: merge('parentheses', { className: 'scene-parentheses' }, { color: DEFAULTS.parentheses.color, bold: DEFAULTS.parentheses.bold, italic: DEFAULTS.parentheses.italic }, true),
            brackets: merge('brackets', { className: 'scene-brackets' }, { color: DEFAULTS.brackets.color, bold: DEFAULTS.brackets.bold, italic: DEFAULTS.brackets.italic }, true),
            entities: merge('entities', { className: 'scene-entity' }, { color: DEFAULTS.entities.color, bold: DEFAULTS.entities.bold, italic: DEFAULTS.entities.italic }, true),
            prefix:   merge('prefix',   { className: 'scene-prefix' },   { color: DEFAULTS.prefix.color,  bold: true, italic: false }),
            default: merge('default', { className: 'scene-default' }, { color: defaultColor, bold: false, italic: false }),
        };
        
        this.marked = new Marked();
        this.setupMarked();
    }
    
    setupMarked() {
        // Custom extensions for quotes, parentheses, and brackets
        const self = this;
        const extensions = [
            // Extension for quoted text
            {
                name: 'quotes',
                level: 'inline',
                start(src) { return src.match(/"/)?.index; },
                tokenizer(src, tokens) {
                    const match = src.match(/^"([^"]+)"/);
                    if (match) {
                        return {
                            type: 'quotes',
                            raw: match[0],
                            text: match[1],
                            tokens: this.lexer.inlineTokens(match[1]),
                        };
                    }
                },
                renderer(token) {
                    const content = this.parser.parseInline(token.tokens);
                    const styles = self.config.quotes;
                    return self.buildSpan('quotes', `"${content}"`, styles);
                },
            },
            
            // Extension for parenthetical text (multiline)
            {
                name: 'parentheses',
                level: 'inline',
                start(src) { return src.match(/\(/)?.index; },
                tokenizer(src, tokens) {
                    const match = src.match(/^\(([\s\S]+?)\)/);
                    if (match) {
                        return {
                            type: 'parentheses',
                            raw: match[0],
                            text: match[1],
                            tokens: this.lexer.inlineTokens(match[1])
                        };
                    }
                },
                renderer(token) {
                    const content = this.parser.parseInline(token.tokens);
                    const styles = self.config.parentheses;
                    return self.buildSpan('parentheses', `(${content})`, styles);
                },
            },
            
            // Extension for bracketed text (multiline)
            {
                name: 'bracketedText',
                level: 'inline',
                start(src) { return src.match(/\[/)?.index; },
                tokenizer(src, tokens) {
                    // Only match brackets that aren't part of a link (multiline)
                    const match = src.match(/^\[([\s\S]+?)\](?!\()/);
                    if (match) {
                        return {
                            type: 'bracketedText',
                            raw: match[0],
                            text: match[1],
                            tokens: this.lexer.inlineTokens(match[1])
                        };
                    }
                },
                renderer(token) {
                    const content = this.parser.parseInline(token.tokens);
                    const styles = self.config.brackets;
                    return self.buildSpan('brackets', `[${content}]`, styles);
                },
            },

            // Extension for entity-mention phrases — verbatim noun phrases the
            // world-state snapshot extracted. Wraps each match in a clickable
            // span so the UI can show an "examine" tooltip. Active only when
            // `parse()` is called with a non-empty mentions list.
            {
                name: 'sceneEntity',
                level: 'inline',
                start(src) {
                    const compiled = self._entityMentions;
                    if (!compiled) return undefined;
                    return src.match(compiled.startRegex)?.index;
                },
                tokenizer(src) {
                    const compiled = self._entityMentions;
                    if (!compiled) return;
                    const match = src.match(compiled.matchRegex);
                    if (!match) return;
                    const phrase = match[0];
                    const entity = compiled.phraseToEntity[phrase.toLowerCase()];
                    if (!entity) return;
                    return {
                        type: 'sceneEntity',
                        raw: phrase,
                        text: phrase,
                        entityName: entity.name,
                        entityKind: entity.kind,
                    };
                },
                renderer(token) {
                    const styles = self.config.entities;
                    const text = escapeHtmlText(token.text);
                    // Appearance toggle disables highlights — emit plain text.
                    if (styles && styles.show === false) {
                        return text;
                    }
                    // Only highlight the first occurrence of each entity per
                    // parse — repeats add visual noise without adding info.
                    // The dedupe lives here (not in tokenizer) because the
                    // custom paragraph renderer re-tokenizes via parseInline,
                    // so the tokenizer fires twice per phrase but the renderer
                    // fires exactly once per visible occurrence.
                    const seenKey = `${token.entityKind}:${token.entityName}`;
                    if (self._entitiesSeenInParse.has(seenKey)) {
                        return text;
                    }
                    self._entitiesSeenInParse.add(seenKey);
                    const name = escapeHtmlAttr(token.entityName);
                    const kind = escapeHtmlAttr(token.entityKind);
                    const styleStr = self.buildStyleString(styles);
                    return `<span class="scene-entity" data-entity-name="${name}" data-entity-kind="${kind}" style="${styleStr}">${text}</span>`;
                },
            }
        ];
        
        // Custom renderer for emphasis (*)
        const renderer = {
            em: ({ text }) => {
                const styles = this.config.emphasis;
                return this.buildSpan('emphasis', text, styles);
            },
            
            // Optionally override other elements
            strong: ({ text }) => {
                if (this.config.strong) {
                    return this.buildElement('strong', text, this.config.strong);
                }
                return `<strong>${text}</strong>`;
            },

            paragraph: (token) => {
                const styles = this.config.default;
                const content = this.marked.parseInline(token.text);
                // Use div instead of span for paragraphs, with CSS class for spacing
                const styleStr = this.buildStyleString(styles);
                return `<div class="${styles.className} scene-paragraph" style="${styleStr}">${content}</div>`;
            },

            // Custom renderer for horizontal rules (---) to match v-divider styling
            hr: () => {
                return '<hr class="scene-hr" style="border: none; border-top: 1px solid rgba(255, 255, 255, 0.12); margin: 16px 0; width: 100%;" />';
            },

            // Disable markdown images
            image: () => {
                return '';
            },
        };
        
        // Apply extensions and renderer
        this.marked.use({ extensions, renderer });
        
        // Configure marked options
        this.marked.use({
            breaks: true,
            gfm: true,
        });
    }
    
    buildSpan(type, content, styles) {
        const styleStr = this.buildStyleString(styles);
        return `<span class="${styles.className}" style="${styleStr}">${content}</span>`;
    }
    
    buildElement(tag, content, styles) {
        const styleStr = this.buildStyleString(styles);
        return `<${tag} class="${styles.className}" style="${styleStr}">${content}</${tag}>`;
    }
    
    buildStyleString(styles) {
        let styleStr = styles.style || '';
        
        // Only add color if it's not null
        if (styles.color !== null && styles.color !== undefined) {
            styleStr += ` color: ${styles.color};`;
        }
        
        // Explicitly set font-weight to prevent inheritance
        if (styles.bold) {
            styleStr += ' font-weight: bold;';
        } else {
            styleStr += ' font-weight: normal;';
        }
        
        // Explicitly set font-style to prevent inheritance
        if (styles.italic) {
            styleStr += ' font-style: italic;';
        } else {
            styleStr += ' font-style: normal;';
        }
        
        return styleStr.trim();
    }
    
    // Remove hidden markup content and collapse surrounding whitespace
    // Handles one level of nesting: outer markers win
    stripHiddenMarkers(text) {
        let result = text;

        // Helper to remove content with one marker type, collapsing whitespace
        const stripMarker = (str, openChar, closeChar) => {
            const open = escapeRegex(openChar);
            const close = escapeRegex(closeChar);
            // Match: optional leading space + marker content + optional trailing space
            // Capture groups to decide which space to remove
            const regex = new RegExp(`( ?)${open}[\\s\\S]+?${close}( ?)`, 'g');
            return str.replace(regex, (match, leadingSpace, trailingSpace) => {
                // Keep a single space if there was space on either side
                if (leadingSpace || trailingSpace) {
                    return ' ';
                }
                // No spaces on either side - remove entirely
                return '';
            });
        };

        // Process brackets first (outer wins - if brackets are hidden, nested parens go too)
        if (!this.config.brackets.show) {
            result = stripMarker(result, '[', ']');
        }

        // Process parentheses (either standalone or nested inside visible brackets)
        if (!this.config.parentheses.show) {
            result = stripMarker(result, '(', ')');
        }

        // Strip leading/trailing whitespace from final result
        return result.trim();
    }

    // Protect newlines inside delimited content before marked processes it
    protectNewlines(text, openChar, closeChar) {
        const open = escapeRegex(openChar);
        const close = escapeRegex(closeChar);
        const regex = new RegExp(`${open}([\\s\\S]+?)${close}`, 'g');
        return text.replace(regex, (_, content) => {
            return openChar + content.replace(/\n/g, '\x00BR\x00') + closeChar;
        });
    }

    parse(text, options = {}) {
        let md = text;

        // Strip hidden markers before any other processing
        md = this.stripHiddenMarkers(md);

        // Protect newlines inside brackets and parentheses before marked processes them
        md = this.protectNewlines(md, '[', ']');
        md = this.protectNewlines(md, '(', ')');

        // Detect "Character Name: " prefix at start of message
        const prefixRegex = /^([^:\n]{1,50}):\s*/; // up to 50 chars before first colon
        const m = md.match(prefixRegex);
        if (m) {
            const prefixStr = m[1] + ':';
            const rest      = md.slice(m[0].length);
            const styled    = this.buildSpan('prefix', prefixStr, this.config.prefix);
            md = styled + ' ' + rest;
        }

        // Stash the compiled mention regex so the entity tokenizer extension
        // can see it during this parse. Cleared on the way out so subsequent
        // parses on this instance don't accidentally inherit it. The seen-set
        // dedupes entities so each one highlights only on its first match.
        this._entityMentions = compileEntityMentions(options.mentions);
        this._entitiesSeenInParse = new Set();
        try {
            let result = this.marked.parse(md);
            // Restore protected newlines as <br> tags
            // eslint-disable-next-line no-control-regex
            result = result.replace(/\x00BR\x00/g, '<br>');
            return result;
        } finally {
            this._entityMentions = null;
            this._entitiesSeenInParse = null;
        }
    }
    
    parseInline(text) {
        return this.marked.parseInline(text);
    }
    
    // Update configuration
    updateConfig(newConfig) {
        this.config = { ...this.config, ...newConfig };
        this.setupMarked(); // Reinitialize with new config
    }
}

// Export a default instance for backward compatibility
export const defaultParser = new SceneTextParser();

// Export parse function for simple usage
export function parseSceneText(text, config = {}) {
    const parser = new SceneTextParser(config);
    return parser.parse(text);
}

// Example usage:
/*
// Create a parser with custom configuration
const parser = new SceneTextParser({
    emphasis: {
        color: '#e74c3c',
        italic: true,
        bold: false
    },
    quotes: {
        color: '#3498db',
        italic: false,
        bold: true
    },
    parentheses: {
        color: '#95a5a6',
        italic: true,
        bold: false
    },
    brackets: {
        color: '#f39c12',
        italic: false,
        bold: true
    }
});

// Parse text
const html = parser.parse('*This is emphasized* and "this is quoted" while (this is parenthetical) and [this is bracketed]');

// Or use the function directly
const html2 = parseSceneText('Some *text* with "quotes"', {
    emphasis: { color: 'red' },
    quotes: { color: 'blue' }
});
*/