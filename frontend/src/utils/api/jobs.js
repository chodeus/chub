/** Jobs API: the job queue under /api/jobs. */

import { apiCore } from './core.js';

export const jobsAPI = {
    /** Job statistics. */
    getStats: (options = {}) => {
        return apiCore.get('/jobs/stats', {
            useCache: true,
            cacheTTL: 30 * 1000, // 30 seconds cache for stats
            ...options,
        });
    },

    /** List jobs, optionally filtered by status, job_type or limit. */
    listJobs: (filters = {}, options = {}) => {
        const params = new URLSearchParams();

        if (filters.status) {
            params.append('status', filters.status);
        }
        if (filters.job_type) {
            params.append('job_type', filters.job_type);
        }
        if (filters.limit) {
            params.append('limit', filters.limit.toString());
        }

        const url = params.toString() ? `/jobs?${params.toString()}` : '/jobs';

        return apiCore.get(url, {
            useCache: true,
            cacheTTL: 10 * 1000, // 10 seconds cache for job lists
            ...options,
        });
    },

    /** One job's details. */
    getJob: (jobId, options = {}) => {
        return apiCore.get(`/jobs/${jobId}`, {
            useCache: true,
            cacheTTL: 5 * 1000, // 5 seconds cache for job details
            ...options,
        });
    },

    /** Requeue a job. The endpoint accepts only error or success jobs. */
    retryJob: (jobId, options = {}) => {
        return apiCore.post(`/jobs/${jobId}/retry`, {}, options);
    },

    /** Delete completed/errored jobs older than `days`. */
    deleteOldJobs: (days = 30) => {
        return apiCore.delete(`/jobs/old?days=${days}`);
    },
};
