/** Guards that a connect resuming after teardown cannot leak an EventSource. */
import { renderHook, act } from '@testing-library/react';

vi.mock('../utils/api/streamAuth.js', () => {
    const state = { resolve: null };
    return {
        ensureStreamToken: () =>
            new Promise(resolve => {
                state.resolve = resolve;
            }),
        __state: state,
    };
});

const streamAuth = await import('../utils/api/streamAuth.js');
const { useModuleEvents } = await import('./useModuleEvents.js');

const opened = [];

class FakeEventSource {
    constructor(url) {
        this.url = url;
        this.closed = false;
        opened.push(this);
    }
    close() {
        this.closed = true;
    }
}

beforeEach(() => {
    opened.length = 0;
    streamAuth.__state.resolve = null;
    vi.stubGlobal('EventSource', FakeEventSource);
});

afterEach(() => vi.unstubAllGlobals());

describe('useModuleEvents', () => {
    it('opens no connection when the token resolves after unmount', async () => {
        const { unmount } = renderHook(() => useModuleEvents());
        unmount();

        await act(async () => streamAuth.__state.resolve('stream-token'));

        expect(opened).toHaveLength(0);
    });

    it('opens no connection when the hook is disabled during the token mint', async () => {
        const { rerender } = renderHook(({ enabled }) => useModuleEvents({ enabled }), {
            initialProps: { enabled: true },
        });
        rerender({ enabled: false });

        await act(async () => streamAuth.__state.resolve('stream-token'));

        expect(opened).toHaveLength(0);
    });

    it('closes the connection it opened when the hook unmounts', async () => {
        const { unmount } = renderHook(() => useModuleEvents());
        await act(async () => streamAuth.__state.resolve('stream-token'));
        expect(opened).toHaveLength(1);

        unmount();

        expect(opened[0].closed).toBe(true);
    });
});
