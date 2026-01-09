import { marked, Marked } from 'marked';

const DEFAULTS = {
    quotes: {
        color: "#FFFFFF",
        italic: false,
        bold: false,
    },
    parentheses: {
        color: "#DB9DC2",
        italic: false,
        bold: false,
    },
    brackets: {
        color: "#DC5D5D",
        italic: false,
        bold: true,
    },
    emphasis: {
        color: "#B39DDB",
        italic: false,        
        bold: false,
    },
    default: {
        color: "#B39DDB",
        italic: true,        
        bold: false,
    },
    prefix: {
        color: "#FFE082",
        italic: false,
        bold: true,
    },
}

// Default colors for different message types when no color is specified
const MESSAGE_TYPE_DEFAULTS = {
    context_investigation: "#D5C0A1",
}

export class SceneTextParser {
    constructor(config = {}) {
        // Determine default color:
        // 1. Use config.defaultColor if explicitly provided
        // 2. Use message type default if messageType is specified
        // 3. Otherwise use DEFAULTS.default.color
        const defaultColor = config.defaultColor ?? 
                            (config.messageType && MESSAGE_TYPE_DEFAULTS[config.messageType]) ?? 
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
            };
        };
        
        this.config = {
            quotes: merge('quotes', { className: 'scene-quotes' }, { color: DEFAULTS.quotes.color, bold: DEFAULTS.quotes.bold, italic: DEFAULTS.quotes.italic }, true),
            emphasis: merge('emphasis', { className: 'scene-emphasis' }, { color: DEFAULTS.emphasis.color, bold: DEFAULTS.emphasis.bold, italic: DEFAULTS.emphasis.italic }, true),
            parentheses: merge('parentheses', { className: 'scene-parentheses' }, { color: DEFAULTS.parentheses.color, bold: DEFAULTS.parentheses.bold, italic: DEFAULTS.parentheses.italic }, true),
            brackets: merge('brackets', { className: 'scene-brackets' }, { color: DEFAULTS.brackets.color, bold: DEFAULTS.brackets.bold, italic: DEFAULTS.brackets.italic }, true),
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
    
    parse(text) {
        let md = text;
        // Detect "Character Name: " prefix at start of message
        const prefixRegex = /^([^:\n]{1,50}):\s*/; // up to 50 chars before first colon
        const m = md.match(prefixRegex);
        if (m) {
            const prefixStr = m[1] + ':';
            const rest      = md.slice(m[0].length);
            const styled    = this.buildSpan('prefix', prefixStr, this.config.prefix);
            md = styled + ' ' + rest;
        }
        return this.marked.parse(md);
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