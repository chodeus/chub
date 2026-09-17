/** Guards that an unparseable date formats as '' rather than NaN/NaN/NaN. */
import { describe, expect, it } from 'vitest';

const { formatDate, formatDateTime, formatTime } = await import('./datetime.js');

describe('datetime formatters reject invalid dates', () => {
    it('returns empty for an invalid Date instance', () => {
        expect(formatDateTime(new Date('nope'))).toBe('');
        expect(formatDate(new Date('nope'))).toBe('');
        expect(formatTime(new Date('nope'))).toBe('');
    });

    // The review cited only the Date branch; the number branch had the same bug.
    it('returns empty for a NaN timestamp', () => {
        expect(formatDateTime(NaN)).toBe('');
        expect(formatDate(NaN)).toBe('');
    });

    it('still formats the values it is given in practice', () => {
        expect(formatDate(new Date(Date.UTC(2026, 8, 17)))).toMatch(/^\d{2}\/\d{2}\/2026$/);
        expect(formatDateTime('2026-09-17 08:30:00')).toMatch(
            /^\d{2}\/\d{2}\/2026 \d{2}:\d{2}:\d{2}$/
        );
        expect(formatDateTime(null)).toBe('');
        expect(formatDateTime('not a date')).toBe('');
    });
});
