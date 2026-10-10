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

    it('gives up after a run of failed requests, counting only consecutive ones', async () => {
        vi.useFakeTimers();
        let calls = 0;
        jobs.tailJobLog.mockImplementation(() => {
            calls += 1;
            // Call 10 succeeds and restarts the count: 20 more failures make 30 calls
            if (calls === 10) return Promise.resolve({ data: { status: 'running' } });
            return Promise.reject(new Error('502'));
        });

        const done = pollJobUntilDone(1, { cancelled: false });
        await vi.advanceTimersByTimeAsync(5 * 60 * 1000);

        await expect(done).resolves.toBe(POLL_UNREACHABLE);
        expect(calls).toBe(30);
    });
});
