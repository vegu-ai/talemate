import { describe, expect, it } from 'vitest';
import { formatProbability } from '@/utils/probability';

describe('formatProbability', () => {
    it('shows two decimals by default', () => {
        expect(formatProbability(0.8)).toBe('0.80');
        expect(formatProbability(0.8234567)).toBe('0.82');
        expect(formatProbability(0.005)).toBe('0.01');
    });

    it('gives 0 and 1 two decimals too', () => {
        expect(formatProbability(0)).toBe('0.00');
        expect(formatProbability(1)).toBe('1.00');
    });

    it('keeps two decimals when the compared value reads differently', () => {
        expect(formatProbability(0.74, 0.8)).toBe('0.74');
        expect(formatProbability(0.8, 0.74)).toBe('0.80');
    });

    it('keeps two decimals when the compared value is the same', () => {
        expect(formatProbability(0.91, 0.91)).toBe('0.91');
    });

    it('adds decimals until a score and its threshold differ', () => {
        expect(formatProbability(0.804, 0.8)).toBe('0.804');
        expect(formatProbability(0.8, 0.804)).toBe('0.80');
        expect(formatProbability(0.7996, 0.8)).toBe('0.7996');
        expect(formatProbability(0.8012, 0.8011)).toBe('0.8012');
        expect(formatProbability(0.8011, 0.8012)).toBe('0.8011');
    });

    it('stops at four decimals', () => {
        expect(formatProbability(0.80001, 0.8)).toBe('0.80');
        expect(formatProbability(0.80004, 0.80001)).toBe('0.80');
    });

    it('compares against an integer threshold', () => {
        expect(formatProbability(0.999, 1)).toBe('0.999');
        expect(formatProbability(1, 0.999)).toBe('1.00');
        expect(formatProbability(0.9951, 1)).toBe('0.995');
    });
});
