import { describe, expect, it } from 'vitest';
import { DEFAULT_REASON_TOKENS, reasonTokensOnEnable } from '@/utils/clientReasoning';

describe('reasonTokensOnEnable', () => {
    it('gives a missing or zero budget the default minimum', () => {
        expect(reasonTokensOnEnable(0)).toBe(DEFAULT_REASON_TOKENS);
        expect(reasonTokensOnEnable(undefined)).toBe(DEFAULT_REASON_TOKENS);
        expect(reasonTokensOnEnable(null)).toBe(DEFAULT_REASON_TOKENS);
        expect(DEFAULT_REASON_TOKENS).toBe(1024);
    });

    it('keeps a budget that is already set', () => {
        expect(reasonTokensOnEnable(512)).toBe(512);
        expect(reasonTokensOnEnable(8192, 1024)).toBe(8192);
    });

    it('respects a larger minimum of the client', () => {
        expect(reasonTokensOnEnable(0, 2048)).toBe(2048);
    });
});
