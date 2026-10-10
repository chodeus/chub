import { jobsAPI } from './api/jobs.js';

export const TERMINAL_STATUSES = ['success', 'error', 'cancelled'];
export const POLL_UNREACHABLE = 'unreachable';
// Give up once requests have failed without a break for this long (timeouts included)
const GIVE_UP_AFTER_MS = 60 * 1000;

// Resolves with the job's terminal status, POLL_UNREACHABLE after a minute of failed
// requests, or undefined once `token.cancelled` flips (unmount, or a superseding run).
export function pollJobUntilDone(jobId, token) {
    return new Promise(resolve => {
        let offset = 0;
        let failingSince = null;
        const poll = () => {
            if (token.cancelled) return resolve();
            const sentAt = Date.now();
            jobsAPI
                .tailJobLog(jobId, offset)
                .then(res => {
                    if (token.cancelled) return resolve();
                    failingSince = null;
                    const data = res?.data || {};
                    if (typeof data.next_offset === 'number') offset = data.next_offset;
                    if (TERMINAL_STATUSES.includes(data.status)) return resolve(data.status);
                    setTimeout(poll, 1500);
                })
                .catch(() => {
                    if (token.cancelled) return resolve();
                    if (failingSince === null) failingSince = sentAt;
                    if (Date.now() - failingSince >= GIVE_UP_AFTER_MS) {
                        return resolve(POLL_UNREACHABLE);
                    }
                    setTimeout(poll, 3000);
                });
        };
        poll();
    });
}
