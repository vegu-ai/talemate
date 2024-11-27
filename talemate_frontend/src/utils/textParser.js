// Define default patterns
const defaultPatterns = [
    {
      type: '"',
      regex: /"([^"]*)"/g,
      extract: match => `"${match[1]}"` // Preserve quotes
    },
    {
      type: '*',
      regex: /\*(.*?)\*/g,
      extract: match => match[1] // Remove asterisks
    }
  ];
  
  export class TextParser {
    constructor(patterns = defaultPatterns) {
      this.patterns = patterns;
    }
  
    parse(text) {
      const parts = [];
      let remaining = text;
  
      while (remaining) {
        let earliestMatch = null;
        let matchedPattern = null;
  
        for (const pattern of this.patterns) {
          pattern.regex.lastIndex = 0;
          const match = pattern.regex.exec(remaining);
          if (match && (!earliestMatch || match.index < earliestMatch.index)) {
            earliestMatch = match;
            matchedPattern = pattern;
          }
        }
  
        if (!earliestMatch) {
          if (remaining) {
            parts.push({ text: remaining, type: '' });
          }
          break;
        }
  
        if (earliestMatch.index > 0) {
          parts.push({
            text: remaining.slice(0, earliestMatch.index),
            type: ''
          });
        }
  
        parts.push({
          text: matchedPattern.extract(earliestMatch),
          type: matchedPattern.type
        });
  
        remaining = remaining.slice(earliestMatch.index + earliestMatch[0].length);
      }
  
      return parts;
    }
  
    // Method to add a new pattern
    addPattern(pattern) {
      this.patterns.push(pattern);
    }
  
    // Method to remove a pattern by type
    removePattern(type) {
      this.patterns = this.patterns.filter(p => p.type !== type);
    }
  }
  
  // Create a default instance
  export const defaultParser = new TextParser();
  
  // Export a convenience function that uses the default parser
  export const parseText = (text) => defaultParser.parse(text);