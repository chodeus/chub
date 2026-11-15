/** Guards that polls append only new lines, and that a refresh in flight cannot commit content for a previous selection. */
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

/** A server read: `reset` replaces the view, otherwise `text` is appended. */
const read = (text, { offset = text.length, id = 'i1', start = 0, reset = true } = {}) => ({
    text,
    offset,
    id,
    start,
    reset,
});

describe('useLogContent', () => {
    beforeEach(() => logsAPI.fetchLogContent.mockReset());

    it('discards a refresh that was in flight when the selection changed', async () => {
        const initial = deferred();
        logsAPI.fetchLogContent.mockReturnValueOnce(initial.promise);
        const { result, rerender } = renderHook(({ mod, file }) => useLogContent(mod, file), {
            initialProps: { mod: 'border_replacerr', file: 'a.log' },
        });
        await act(async () => initial.settle(read('content for a.log')));
        await waitFor(() => expect(result.current.logText).toBe('content for a.log'));

        // A poll-driven refresh starts, then the user switches file before it lands.
        const refresh = deferred();
        logsAPI.fetchLogContent.mockReturnValueOnce(refresh.promise);
        act(() => {
            result.current.refresh();
        });
        logsAPI.fetchLogContent.mockReturnValueOnce(deferred().promise);
        rerender({ mod: 'border_replacerr', file: 'b.log' });

        await act(async () => refresh.settle(read('stale content for a.log')));

        expect(result.current.logText).not.toBe('stale content for a.log');
    });

    it('aborts the refresh that was in flight when the selection changed', async () => {
        const initial = deferred();
        logsAPI.fetchLogContent.mockReturnValueOnce(initial.promise);
        const { result, rerender } = renderHook(({ file }) => useLogContent('mod', file), {
            initialProps: { file: 'a.log' },
        });
        await act(async () => initial.settle(read('a')));

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

    it('appends what a poll adds, sending the offset, id and view start of the last read', async () => {
        logsAPI.fetchLogContent.mockResolvedValueOnce(
            read('a\n', { offset: 2, id: 'x', start: 3 })
        );
        const { result } = renderHook(() => useLogContent('mod', 'a.log'));
        await waitFor(() => expect(result.current.logText).toBe('a\n'));

        logsAPI.fetchLogContent.mockResolvedValueOnce(
            read('b\n', { offset: 4, id: 'x', start: 3, reset: false })
        );
        await act(() => result.current.refresh());

        expect(result.current.logText).toBe('a\nb\n');
        expect(logsAPI.fetchLogContent.mock.calls.at(-1)[3]).toEqual({
            offset: 2,
            id: 'x',
            start: 3,
        });
    });

    it('replaces the view when the server starts over, and reports what it left out', async () => {
        logsAPI.fetchLogContent.mockResolvedValueOnce(read('old\n', { offset: 4 }));
        const { result } = renderHook(() => useLogContent('mod', 'a.log'));
        await waitFor(() => expect(result.current.logText).toBe('old\n'));

        logsAPI.fetchLogContent.mockResolvedValueOnce(
            read('new\n', { offset: 9000, start: 8996, id: 'i2' })
        );
        await act(() => result.current.refresh());

        expect([result.current.logText, result.current.skippedBytes]).toEqual(['new\n', 8996]);
    });

    it('clears a failed first read once a poll gets the log', async () => {
        vi.spyOn(console, 'error').mockImplementation(() => {});
        logsAPI.fetchLogContent.mockRejectedValueOnce(
            new Error('Log request failed with status 503')
        );
        const { result } = renderHook(() => useLogContent('mod', 'a.log'));
        await waitFor(() => expect(result.current.error?.message).toMatch('503'));

        logsAPI.fetchLogContent.mockResolvedValueOnce(read('a\n'));
        await act(() => result.current.refresh());

        expect([result.current.error, result.current.logText]).toEqual([null, 'a\n']);
    });

    it('starts a new selection over from offset 0, clearing the old file', async () => {
        logsAPI.fetchLogContent.mockResolvedValueOnce(
            read('a\n', { offset: 2, id: 'x', start: 5 })
        );
        const { result, rerender } = renderHook(({ file }) => useLogContent('mod', file), {
            initialProps: { file: 'a.log' },
        });
        await waitFor(() => expect(result.current.skippedBytes).toBe(5));

        logsAPI.fetchLogContent.mockReturnValueOnce(deferred().promise);
        rerender({ file: 'b.log' });

        expect(logsAPI.fetchLogContent.mock.calls.at(-1)[3]).toEqual({
            offset: 0,
            id: '',
            start: 0,
        });
        expect([result.current.logText, result.current.skippedBytes]).toEqual(['', 0]);
    });
});
