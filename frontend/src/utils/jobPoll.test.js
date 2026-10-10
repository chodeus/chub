const jobs = { tailJobLog: vi.fn() };
vi.mock('./api/jobs.js', () => ({ jobsAPI: jobs }));

const { pollJobUntilDone } = await import('./jobPoll.js');

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
});
