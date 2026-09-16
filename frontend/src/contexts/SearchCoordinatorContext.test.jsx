import { renderHook, act } from '@testing-library/react';
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

    it('ignores a stored value that is not an array', () => {
        localStorage.setItem(HISTORY_KEY, JSON.stringify({ term: 'not an array' }));

        const { result } = mountHistory();

        expect(result.current.getHistory()).toEqual([]);
    });
});
