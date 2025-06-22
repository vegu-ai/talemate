import { marked, Marked } from 'marked';

const DEFAULTS = {
    quotes: {
        color: "#FFFFFF",
        italic: false,
        bold: false,
    },
    parentheses: {
        color: "#B39DDB",
        italic: true,
        bold: false,
    },
    brackets: {
        color: "#B39DDB",
        italic: true,
        bold: false,
    },
    emphasis: {
        color: "#B39DDB",
        italic: true,        
        bold: false,
    },
    default: {
        color: "#B39DDB",
        italic: true,        
        bold: false,
    },
}

export class SceneTextParser {
    constructor(config = {}) {
        // Helper to merge a user-supplied style object with defaults
        const merge = (key, defaultObj, defaults) => {
            const user = config[key] ?? {};
            return {
                className: defaultObj.className,
                style: user.style ?? '',
                color: user.color != null ? user.color : defaults.color,
                bold: user.bold != null ? user.bold : (defaults.bold ?? false),
                italic: user.italic != null ? user.italic : (defaults.italic ?? false),
            };
        };

        this.config = {
            quotes: merge('quotes', { className: 'scene-quotes' }, { color: DEFAULTS.quotes.color, bold: DEFAULTS.quotes.bold, italic: DEFAULTS.quotes.italic }),
            emphasis: merge('emphasis', { className: 'scene-emphasis' }, { color: DEFAULTS.emphasis.color, bold: DEFAULTS.emphasis.bold, italic: DEFAULTS.emphasis.italic }),
            parentheses: merge('parentheses', { className: 'scene-parentheses' }, { color: DEFAULTS.parentheses.color, bold: DEFAULTS.parentheses.bold, italic: DEFAULTS.parentheses.italic }),
            brackets: merge('brackets', { className: 'scene-brackets' }, { color: DEFAULTS.brackets.color, bold: DEFAULTS.brackets.bold, italic: DEFAULTS.brackets.italic }),
            default: merge('default', { className: 'scene-default' }, { color: DEFAULTS.default.color, bold: false, italic: false }),
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
            
            // Extension for parenthetical text
            {
                name: 'parentheses',
                level: 'inline',
                start(src) { return src.match(/\(/)?.index; },
                tokenizer(src, tokens) {
                    const match = src.match(/^\(([^)]+)\)/);
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
            
            // Extension for bracketed text
            {
                name: 'bracketedText',
                level: 'inline',
                start(src) { return src.match(/\[/)?.index; },
                tokenizer(src, tokens) {
                    // Only match brackets that aren't part of a link
                    const match = src.match(/^\[([^\]]+)\](?!\()/);
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
                return this.buildSpan('default', content, styles);
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
        
        if (styles.bold) {
            styleStr += ' font-weight: bold;';
        }
        
        if (styles.italic) {
            styleStr += ' font-style: italic;';
        }
        
        return styleStr.trim();
    }
    
    parse(text) {
        return this.marked.parse(text);
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