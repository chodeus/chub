/** Guards suggestion activation, focus return, list dismissal, and the blur timer. */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';

const coordinator = vi.hoisted(() => ({
    getSearchState: () => ({ term: '' }),
    search: null,
    clearSearch() {},
}));
vi.mock('../../contexts/SearchCoordinatorContext.jsx', () => ({
    useSearchCoordinator: () => coordinator,
}));

const SearchInterface = (await import('./SearchInterface.jsx')).default;

const renderSearch = () =>
    render(
        <MemoryRouter>
            <SearchInterface searchPageType="media" suggestions={['dune', 'alien']} />
            <button type="button">After</button>
        </MemoryRouter>
    );

describe('SearchInterface suggestions', () => {
    beforeEach(() => {
        coordinator.search = vi.fn();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('selects a suggestion from the keyboard exactly once', async () => {
        const user = userEvent.setup();
        renderSearch();
        await user.click(screen.getByRole('textbox'));
        await user.tab();
        expect(screen.getByRole('button', { name: /dune/ })).toHaveFocus();

        await user.keyboard('{Enter}');

        expect(coordinator.search).toHaveBeenCalledTimes(1);
        expect(coordinator.search).toHaveBeenCalledWith('media', 'dune', { immediate: true });
    });

    it('selects a clicked suggestion exactly once', async () => {
        const user = userEvent.setup();
        renderSearch();
        await user.click(screen.getByRole('textbox'));

        await user.click(screen.getByRole('button', { name: /alien/ }));

        expect(coordinator.search).toHaveBeenCalledTimes(1);
        expect(coordinator.search).toHaveBeenCalledWith('media', 'alien', { immediate: true });
    });

    it('returns focus to the input and closes the list after a keyboard select', async () => {
        const user = userEvent.setup();
        renderSearch();
        const input = screen.getByRole('textbox');
        await user.click(input);
        await user.tab();

        await user.keyboard('{Enter}');

        expect(input).toHaveFocus();
        expect(screen.queryByRole('list', { name: 'Recent searches' })).not.toBeInTheDocument();
    });

    it('closes the list when focus tabs out of the last suggestion', async () => {
        const user = userEvent.setup();
        renderSearch();
        await user.click(screen.getByRole('textbox'));
        await user.tab();
        await user.tab();
        expect(screen.getByRole('button', { name: /alien/ })).toHaveFocus();

        await user.tab();

        expect(screen.getByRole('button', { name: 'After' })).toHaveFocus();
        await waitFor(() =>
            expect(screen.queryByRole('list', { name: 'Recent searches' })).not.toBeInTheDocument()
        );
    });

    it('keeps the list open when the input is refocused within the blur delay', () => {
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
        renderSearch();
        const input = screen.getByRole('textbox');
        fireEvent.focus(input);
        fireEvent.blur(input);
        fireEvent.focus(input);

        act(() => vi.advanceTimersByTime(200));

        expect(screen.getByRole('list', { name: 'Recent searches' })).toBeInTheDocument();
    });

    it('leaves no pending blur timer after unmount', () => {
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
        const { unmount } = renderSearch();
        const input = screen.getByRole('textbox');
        fireEvent.focus(input);
        fireEvent.blur(input);
        expect(vi.getTimerCount()).toBe(1);

        unmount();

        expect(vi.getTimerCount()).toBe(0);
    });
});
