import { jobsAPI } from './api/jobs.js';

export const TERMINAL_STATUSES = ['success', 'error', 'cancelled'];
export const POLL_UNREACHABLE = 'unreachable';
// Give up after this many failed requests in a row (about a minute)
const MAX_FAILED_POLLS = 20;

// Resolves with the job's terminal status, POLL_UNREACHABLE after repeated failed
// requests, or undefined once `token.cancelled` flips (unmount, or a superseding run).
export function pollJobUntilDone(jobId, token) {
    return new Promise(resolve => {
        let offset = 0;
        let failures = 0;
        const poll = () => {
            if (token.cancelled) return resolve();
            jobsAPI
                .tailJobLog(jobId, offset)
                .then(res => {
                    if (token.cancelled) return resolve();
                    failures = 0;
                    const data = res?.data || {};
                    if (typeof data.next_offset === 'number') offset = data.next_offset;
                    if (TERMINAL_STATUSES.includes(data.status)) return resolve(data.status);
                    setTimeout(poll, 1500);
                })
                .catch(() => {
                    if (token.cancelled) return resolve();
                    failures += 1;
                    if (failures >= MAX_FAILED_POLLS) return resolve(POLL_UNREACHABLE);
                    setTimeout(poll, 3000);
                });
        };
        poll();
    });
}
