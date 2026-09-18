/** Logs API: module and file listing, tailed content, and downloads. */

import { apiCore } from './core.js';
import { downloadBlob } from '../download.js';

export const logsAPI = {
    /** Available log modules. */
    fetchLogModules: async (forceRefresh = false) => {
        const response = await apiCore.get('/logs', {
            useCache: !forceRefresh,
            cacheTTL: 5 * 60 * 1000, // 5 minutes
        });
        return response.data?.modules || [];
    },

    /** Log files for one module. */
    fetchLogFiles: async (moduleName, forceRefresh = false) => {
        if (!moduleName) return [];

        // Let failures reject: useLogFiles already sets an error state, and
        // swallowing to [] renders "no log files" for a request that broke.
        const response = await apiCore.get(`/logs/${moduleName}`, {
            useCache: !forceRefresh,
            cacheTTL: 5 * 60 * 1000, // 5 minutes
        });
        return response.data?.files || [];
    },

    /** Log content, sending `tail=N` so multi-MB files don't ship whole each poll.
     *  `tail = 0` requests the full file. */
    fetchLogContent: async (moduleName, fileName, signal, tail = 5000) => {
        if (!moduleName || !fileName) return '';

        try {
            const headers = {};
            try {
                const token = localStorage.getItem('chub-auth-token');
                if (token) {
                    headers['Authorization'] = `Bearer ${token}`;
                }
            } catch {
                /* localStorage unavailable */
            }
            const qs = tail > 0 ? `?tail=${tail}` : '';
            const res = await fetch(`/api/logs/${moduleName}/${fileName}${qs}`, {
                headers,
                signal,
            });
            // Reject like downloadLogFile does: '' is a legitimate empty file, so
            // returning it for a failure hid the error from useLogContent's catch.
            if (!res.ok) throw new Error(`Log request failed with status ${res.status}`);
            return await res.text();
        } catch (error) {
            // AbortError is the caller cancelling, not a failure worth logging.
            if (error?.name !== 'AbortError') console.error('Failed to fetch log content:', error);
            throw error;
        }
    },

    /** Download URL for a log file. */
    getLogDownloadUrl: (moduleName, fileName) => {
        if (!moduleName || !fileName) return '';
        return `/api/logs/${moduleName}/${fileName}`;
    },

    /** Download a log file. Fetches with the auth header, or a 401 body would be
     *  saved as the file. */
    downloadLogFile: async (moduleName, fileName) => {
        if (!moduleName || !fileName) {
            throw new Error('Module name and file name are required');
        }

        const headers = {};
        try {
            const token = localStorage.getItem('chub-auth-token');
            if (token) {
                headers['Authorization'] = `Bearer ${token}`;
            }
        } catch {
            /* localStorage unavailable */
        }

        const res = await fetch(`/api/logs/${moduleName}/${fileName}`, { headers });
        if (!res.ok) {
            throw new Error(`Download failed with status ${res.status}`);
        }

        downloadBlob(await res.blob(), fileName);
    },
};
