const jobs = { tailJobLog: vi.fn() };
vi.mock('./api/jobs.js', () => ({ jobsAPI: jobs }));

const { POLL_UNREACHABLE, pollJobUntilDone } = await import('./jobPoll.js');

describe('pollJobUntilDone', () => {
    afterEach(() => {
        vi.useRealTimers();
    });

    it('resolves with the terminal status', async () => {
        jobs.tailJobLog.mockResolvedValue({ data: { status: 'success', next_offset: 0 } });

        await expect(pollJobUntilDone(1, { cancelled: false })).resolves.toBe('success');
    });

    it('settles when a request fails after the wait was cancelled', async () => {
        const token = { cancelled: false };
        let fail;
        jobs.tailJobLog.mockReturnValue(new Promise((_, reject) => (fail = reject)));

        const done = pollJobUntilDone(1, token);
        token.cancelled = true;
        fail(new Error('network'));

        await expect(done).resolves.toBeUndefined();
    });

    it('sends nothing more once cancelled while waiting for the next poll', async () => {
        vi.useFakeTimers();
        const token = { cancelled: false };
        jobs.tailJobLog.mockResolvedValue({ data: { status: 'running', next_offset: 0 } });

        const done = pollJobUntilDone(1, token);
        await vi.advanceTimersByTimeAsync(0);
        token.cancelled = true;
        await vi.advanceTimersByTimeAsync(1500);

        await expect(done).resolves.toBeUndefined();
        expect(jobs.tailJobLog).toHaveBeenCalledTimes(1);
    });

    const settled = promise => {
        const state = { value: 'pending' };
        promise.then(v => (state.value = v));
        return state;
    };

    it('gives up after a minute of fast failures, not before', async () => {
        vi.useFakeTimers();
        jobs.tailJobLog.mockRejectedValue(new Error('502'));

        const state = settled(pollJobUntilDone(1, { cancelled: false }));
        await vi.advanceTimersByTimeAsync(57_000);
        const early = state.value;
        await vi.advanceTimersByTimeAsync(4_000);

        expect(early).toBe('pending');
        expect(state.value).toBe(POLL_UNREACHABLE);
    });

    it('counts the minute from the start of a failing request, so timeouts count', async () => {
        vi.useFakeTimers();
        jobs.tailJobLog.mockImplementation(
            () => new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 30_000))
        );

        const state = settled(pollJobUntilDone(1, { cancelled: false }));
        await vi.advanceTimersByTimeAsync(64_000);

        expect(state.value).toBe(POLL_UNREACHABLE);
        expect(jobs.tailJobLog).toHaveBeenCalledTimes(2);
    });

    it('a successful poll restarts the minute', async () => {
        vi.useFakeTimers();
        let calls = 0;
        jobs.tailJobLog.mockImplementation(() => {
            calls += 1;
            if (calls === 10) return Promise.resolve({ data: { status: 'running' } });
            return Promise.reject(new Error('502'));
        });

        const state = settled(pollJobUntilDone(1, { cancelled: false }));
        await vi.advanceTimersByTimeAsync(80_000);
        const afterReset = state.value;
        await vi.advanceTimersByTimeAsync(20_000);

        expect(afterReset).toBe('pending');
        expect(state.value).toBe(POLL_UNREACHABLE);
    });
});
