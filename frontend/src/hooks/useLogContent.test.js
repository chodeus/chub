/** Guards that a refresh still in flight cannot commit content for a previous selection. */
import { renderHook, act, waitFor } from '@testing-library/react';

vi.mock('../utils/api/logs.js', () => {
    const fetchLogContent = vi.fn();
    return { logsAPI: { fetchLogContent } };
});

const { logsAPI } = await import('../utils/api/logs.js');
const { useLogContent } = await import('./useLogContent.js');

/** A request this test settles by hand. */
const deferred = () => {
    let settle;
    const promise = new Promise(resolve => {
        settle = resolve;
    });
    return { promise, settle };
};

describe('useLogContent', () => {
    beforeEach(() => logsAPI.fetchLogContent.mockReset());

    it('discards a refresh that was in flight when the selection changed', async () => {
        const initial = deferred();
        logsAPI.fetchLogContent.mockReturnValueOnce(initial.promise);
        const { result, rerender } = renderHook(({ mod, file }) => useLogContent(mod, file), {
            initialProps: { mod: 'border_replacerr', file: 'a.log' },
        });
        await act(async () => initial.settle('content for a.log'));
        await waitFor(() => expect(result.current.logText).toBe('content for a.log'));

        // A poll-driven refresh starts, then the user switches file before it lands.
        const refresh = deferred();
        logsAPI.fetchLogContent.mockReturnValueOnce(refresh.promise);
        act(() => {
            result.current.refresh();
        });
        logsAPI.fetchLogContent.mockReturnValueOnce(deferred().promise);
        rerender({ mod: 'border_replacerr', file: 'b.log' });

        await act(async () => refresh.settle('stale content for a.log'));

        expect(result.current.logText).not.toBe('stale content for a.log');
    });

    it('aborts the refresh that was in flight when the selection changed', async () => {
        const initial = deferred();
        logsAPI.fetchLogContent.mockReturnValueOnce(initial.promise);
        const { result, rerender } = renderHook(({ file }) => useLogContent('mod', file), {
            initialProps: { file: 'a.log' },
        });
        await act(async () => initial.settle('a'));

        const refresh = deferred();
        logsAPI.fetchLogContent.mockReturnValueOnce(refresh.promise);
        act(() => {
            result.current.refresh();
        });
        // Third argument is the AbortSignal the hook handed this refresh.
        const refreshSignal = logsAPI.fetchLogContent.mock.calls.at(-1)[2];
        logsAPI.fetchLogContent.mockReturnValueOnce(deferred().promise);
        rerender({ file: 'b.log' });

        expect(refreshSignal.aborted).toBe(true);
    });
});
