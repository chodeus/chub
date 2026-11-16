/** Logs API: module and file listing, content read by offset, and downloads. */

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

    /** One view read: from `offset` 0 the log (its last VIEW_CAP bytes when bigger), then the lines added since,
     *  or a new view when `reset`. Resolves `{text, offset, id, start, reset}`; pass `offset`, `id` and `start` back. */
    fetchLogContent: async (
        moduleName,
        fileName,
        signal,
        { offset = 0, id = '', start = 0 } = {}
    ) => {
        if (!moduleName || !fileName) return { text: '', offset: 0, id: '', start: 0, reset: true };

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
            const qs = new URLSearchParams({ offset: String(offset), id, start: String(start) });
            const res = await fetch(`/api/logs/${moduleName}/${fileName}?${qs}`, {
                headers,
                signal,
            });
            // Reject like downloadLogFile does: '' is a legitimate empty file, so
            // returning it for a failure hid the error from useLogContent's catch.
            if (!res.ok) throw new Error(`Log request failed with status ${res.status}`);
            const text = await res.text();
            const header = name => {
                const value = res.headers.get(name);
                if (value === null) throw new Error(`Log response has no ${name} header`);
                return value;
            };
            const position = name => {
                const n = Number.parseInt(header(name), 10);
                if (!Number.isFinite(n)) throw new Error(`Log response has a bad ${name} header`);
                return n;
            };
            return {
                text,
                offset: position('X-Log-Offset'),
                id: header('X-Log-Id'),
                start: position('X-Log-Start'),
                reset: header('X-Log-Reset') === '1',
            };
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
