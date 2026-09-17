/** Guards useRecentSearches against a corrupted or foreign localStorage value. */
import { renderHook, act } from '@testing-library/react';
import { useRecentSearches } from './useRecentSearches.js';

const KEY = 'chub_recent_searches';

afterEach(() => localStorage.removeItem(KEY));

describe('useRecentSearches', () => {
    it.each([
        ['an object', '{}'],
        ['a bare string', '"term"'],
        ['a number', '5'],
    ])('falls back to an empty list when storage holds %s', (_, stored) => {
        localStorage.setItem(KEY, stored);

        const { result } = renderHook(() => useRecentSearches());

        expect(result.current.recentSearches).toEqual([]);
    });

    it('drops non-string entries rather than handing them to consumers', () => {
        localStorage.setItem(KEY, JSON.stringify(['ok', 5, null, 'fine']));

        const { result } = renderHook(() => useRecentSearches());

        expect(result.current.recentSearches).toEqual(['ok', 'fine']);
    });

    it('still records a search after a corrupted value', () => {
        // Without the guard this throws: prev.filter is not a function.
        localStorage.setItem(KEY, '{}');
        const { result } = renderHook(() => useRecentSearches());

        act(() => result.current.addSearch('poster'));

        expect(result.current.recentSearches).toEqual(['poster']);
    });
});
