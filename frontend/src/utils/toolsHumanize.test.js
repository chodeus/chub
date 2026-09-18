/** Guards that humanize honours its declared string return for every input. */
import { describe, expect, it } from 'vitest';

const { humanize } = await import('./tools.js');

describe('humanize', () => {
    it('returns a string for a truthy non-string', () => {
        expect(humanize(42)).toBe('');
        expect(humanize(true)).toBe('');
        expect(humanize(['a'])).toBe('');
        expect(humanize({})).toBe('');
    });

    it('keeps the documented empty results for absent input', () => {
        expect(humanize(null)).toBe('');
        expect(humanize(undefined)).toBe('');
        expect(humanize('')).toBe('');
        expect(humanize(0)).toBe('');
    });

    it('still humanizes the snake_case keys every caller passes', () => {
        expect(humanize('user_profile_name')).toBe('User Profile Name');
        expect(humanize('api_key')).toBe('Api Key');
        expect(humanize('poster_renamerr')).toBe('Poster Renamerr');
    });
});
