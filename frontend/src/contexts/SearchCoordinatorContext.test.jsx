import { renderHook, act, waitFor } from '@testing-library/react';
import { SearchCoordinatorProvider, useSearchCoordinator } from './SearchCoordinatorContext.jsx';

const HISTORY_KEY = 'chub-search-history';

const mountHistory = () =>
    renderHook(() => useSearchCoordinator(), { wrapper: SearchCoordinatorProvider });

describe('SearchCoordinatorProvider history', () => {
    beforeEach(() => {
        localStorage.clear();
    });

    it('persists a cleared history instead of leaving the old entries stored', () => {
        localStorage.setItem(
            HISTORY_KEY,
            JSON.stringify([{ term: 'dune', searchType: 'media', timestamp: 1 }])
        );
        const { result } = mountHistory();
        expect(result.current.getHistory()).toHaveLength(1);

        act(() => {
            result.current.clearHistory();
        });

        expect(result.current.getHistory()).toEqual([]);
        // Without this write the next mount loads the old entry straight back.
        expect(JSON.parse(localStorage.getItem(HISTORY_KEY))).toEqual([]);
    });

    it('drops stored entries that would throw when read back', () => {
        localStorage.setItem(
            HISTORY_KEY,
            JSON.stringify([
                { term: 'dune', searchType: 'media', timestamp: 1 },
                { term: 42, searchType: 'media' },
                null,
            ])
        );

        const { result } = mountHistory();

        expect(result.current.getHistory()).toHaveLength(1);
        expect(() => result.current.getSuggestions('media', 'du')).not.toThrow();
    });

    it('ignores a stored value that is not an array', () => {
        localStorage.setItem(HISTORY_KEY, JSON.stringify({ term: 'not an array' }));

        const { result } = mountHistory();

        expect(result.current.getHistory()).toEqual([]);
    });
});

describe('SearchCoordinatorProvider results', () => {
    it("drops an old term's results that land between the new term's commit and its effects", async () => {
        let answerOld;
        const searchFn = vi.fn(() => new Promise(r => (answerOld = r)));
        const { result } = renderHook(() => useSearchCoordinator(), {
            wrapper: SearchCoordinatorProvider,
        });
        act(() => result.current.registerSearchHandler('media', searchFn));
        act(() => result.current.search('media', 'old', { immediate: true }));
        await waitFor(() => expect(searchFn).toHaveBeenCalledTimes(1));

        // Outside act, so React commits 'new' in its own task; the old answer is queued right behind it.
        await Promise.resolve().then(() => {
            result.current.search('media', 'new');
            setImmediate(() => answerOld({ data: { items: [{ id: 1 }] } }));
        });
        await waitFor(() => expect(result.current.getSearchState('media').term).toBe('new'));
        await new Promise(r => setTimeout(r, 20));

        expect(result.current.getSearchState('media').results).toEqual([]);
    });

    it("keeps an old term's failure off the new search", async () => {
        let failOld;
        const searchFn = vi.fn(() => new Promise((_, reject) => (failOld = reject)));
        const { result } = renderHook(() => useSearchCoordinator(), {
            wrapper: SearchCoordinatorProvider,
        });
        act(() => result.current.registerSearchHandler('media', searchFn));
        act(() => result.current.search('media', 'old', { immediate: true }));
        await waitFor(() => expect(searchFn).toHaveBeenCalledTimes(1));
        act(() => result.current.search('media', 'new'));

        await act(async () => failOld(new Error('timed out')));

        const state = result.current.getSearchState('media');
        expect(state.term).toBe('new');
        expect(state.status).toBe(result.current.searchStatus.SEARCHING);
        expect(state.error).toBeNull();
    });
});
