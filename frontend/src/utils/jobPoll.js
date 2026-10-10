import { jobsAPI } from './api/jobs.js';

export const TERMINAL_STATUSES = ['success', 'error', 'cancelled'];

// Resolves with the job's terminal status, or undefined once `token.cancelled`
// flips (unmount, or a superseding run).
export function pollJobUntilDone(jobId, token) {
    return new Promise(resolve => {
        let offset = 0;
        const poll = () => {
            if (token.cancelled) return resolve();
            jobsAPI
                .tailJobLog(jobId, offset)
                .then(res => {
                    if (token.cancelled) return resolve();
                    const data = res?.data || {};
                    if (typeof data.next_offset === 'number') offset = data.next_offset;
                    if (TERMINAL_STATUSES.includes(data.status)) return resolve(data.status);
                    setTimeout(poll, 1500);
                })
                .catch(() => {
                    if (token.cancelled) return resolve();
                    setTimeout(poll, 3000);
                });
        };
        poll();
    });
}
