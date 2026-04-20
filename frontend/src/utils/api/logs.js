/**
 * CHUB Logs API Module
 *
 * Handles log file access, content retrieval, and external log sharing:
 * - Log module listing
 * - Log file retrieval for specific modules
 * - Log content fetching
 * - Log download URLs
 * - External log upload (dpaste)
 */

import { apiCore } from './core.js';

/**
 * Logs API client for file-based log viewing
 */
export const logsAPI = {
    /**
     * Fetch available log modules
     * @param {boolean} forceRefresh - Bypass cache if true
     * @returns {Promise<Array<string>>} List of module names
     */
    fetchLogModules: async (forceRefresh = false) => {
        const response = await apiCore.get('/logs', {
            useCache: !forceRefresh,
            cacheTTL: 5 * 60 * 1000, // 5 minutes
        });
        return response.data?.modules || [];
    },

    /**
     * Fetch log files for specific module
     * @param {string} moduleName - Module name
     * @param {boolean} forceRefresh - Bypass cache if true
     * @returns {Promise<Array<string>>} List of log file names
     */
    fetchLogFiles: async (moduleName, forceRefresh = false) => {
        if (!moduleName) return [];

        try {
            const response = await apiCore.get(`/logs/${moduleName}`, {
                useCache: !forceRefresh,
                cacheTTL: 5 * 60 * 1000, // 5 minutes
            });
            return response.data?.files || [];
        } catch (error) {
            console.error('Failed to fetch log files:', error);
            return [];
        }
    },

    /**
     * Fetch log file content.
     * Passes `tail=N` to the backend so multi-MB logs only ship the last N
     * lines rather than the whole file each poll.
     * @param {string} moduleName - Module name
     * @param {string} fileName - Log file name
     * @param {AbortSignal} [signal] - Optional AbortSignal to cancel the request
     * @param {number} [tail=5000] - Max lines to request from the tail; 0 = full file
     * @returns {Promise<string>} Log file content as text
     */
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
            if (!res.ok) return '';
            return await res.text();
        } catch (error) {
            if (error?.name === 'AbortError') throw error;
            console.error('Failed to fetch log content:', error);
            return '';
        }
    },

    /**
     * Get log download URL
     * @param {string} moduleName - Module name
     * @param {string} fileName - Log file name
     * @returns {string} Download URL for log file
     */
    getLogDownloadUrl: (moduleName, fileName) => {
        if (!moduleName || !fileName) return '';
        return `/api/logs/${moduleName}/${fileName}`;
    },

    /**
     * Download a log file to the user's disk. Fetches with the auth header
     * so the backend can't reject with 401 (which would otherwise be saved
     * as the file body).
     * @param {string} moduleName - Module name
     * @param {string} fileName - Log file name
     * @returns {Promise<void>}
     * @throws {Error} If the fetch fails or the server returns non-OK
     */
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

        const blob = await res.blob();
        const objectUrl = URL.createObjectURL(blob);
        try {
            const link = document.createElement('a');
            link.href = objectUrl;
            link.download = fileName;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        } finally {
            URL.revokeObjectURL(objectUrl);
        }
    },

    /**
     * Upload log content to external dpaste service
     * @param {string} logContent - Log content to upload
     * @returns {Promise<Object>} Upload result with URL
     * @throws {Error} If upload fails
     */
    uploadLogToPaste: async logContent => {
        if (!logContent) {
            throw new Error('No log content provided');
        }

        const response = await fetch('https://dpaste.com/api/v2/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({
                content: logContent,
                syntax: 'text',
                expiry_days: '1',
            }),
        });

        if (!response.ok) {
            throw new Error(`Upload failed with status ${response.status}`);
        }

        const responseText = await response.text();

        // dpaste returns the URL as plain text
        return {
            success: true,
            url: responseText.trim(),
            message: 'Log uploaded successfully',
        };
    },
};
