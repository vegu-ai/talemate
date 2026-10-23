import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

function sources(directory) {
    return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
        const path = join(directory, entry.name);
        if (entry.isDirectory()) return sources(path);
        return /\.(vue|js)$/.test(entry.name) ? [path] : [];
    });
}

describe('decision model defaults come from the backend', () => {
    it('names no default decision model in the frontend', () => {
        const holders = sources('src').filter(path => readFileSync(path, 'utf8').includes('jev-1.13'));
        expect(holders).toEqual([]);
    });

    it('starts a new decision check without a threshold of its own', () => {
        const source = readFileSync('src/components/WritingStyleDecisionChecks.vue', 'utf8');
        expect(source).not.toMatch(/threshold:\s*0?\.\d/);
        expect(source).toContain('threshold: this.defaultThreshold');
    });
});
