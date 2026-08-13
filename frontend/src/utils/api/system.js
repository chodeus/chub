/**
 * CHUB System API Module
 *
 * Handles system-level operations using REAL CHUB endpoints:
 * - GET /api/version - Application version
 * - GET /api/directory - Directory listing
 * - POST /api/test - Test endpoint
 * - POST /api/folder - Create directory
 */

import { apiCore } from './core.js';
import { downloadBlob } from '../download.js';

/**
 * System API client matching actual CHUB backend endpoints
 */
export const systemAPI = {
    /**
     * Get application version
     * @param {Object} options - Request options
     * @returns {Promise<Object>} Version information
     */
    getVersion: (options = {}) => {
        return apiCore.get('/version', {
            useCache: true,
            cacheTTL: 60 * 60 * 1000, // 1 hour cache for version
            ...options,
        });
    },

    /**
     * On-demand update check against the remote release manifest.
     * @returns {Promise<Object>} { local_version, remote_version, branch, update_available, checked }
     */
    checkForUpdate: (options = {}) => {
        return apiCore.get('/version/check', { ...options });
    },

    /**
     * List saved config+db backups in the backups directory.
     * @returns {Promise<Object>} { backups: [{ filename, size_bytes, created }] }
     */
    listBackups: (options = {}) => {
        return apiCore.get('/backups', { ...options });
    },

    /**
     * Create a backup and download the zip to the user's disk. Fetches with the
     * auth header so a 401 isn't saved as the file body.
     * @returns {Promise<void>}
     */
    downloadBackup: async () => {
        const headers = {};
        try {
            const token = localStorage.getItem('chub-auth-token');
            if (token) headers['Authorization'] = `Bearer ${token}`;
        } catch {
            /* localStorage unavailable */
        }
        const res = await fetch('/api/backup', { method: 'POST', headers });
        if (!res.ok) throw new Error(`Backup failed with status ${res.status}`);
        const disposition = res.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename=([^;]+)/);
        const filename = match ? match[1].trim() : 'chub-backup.zip';
        downloadBlob(await res.blob(), filename);
    },

    /**
     * Restore config from an uploaded backup zip (multipart).
     * @param {File} file - The backup zip
     * @returns {Promise<Object>} Restore result
     */
    restoreBackup: (file, options = {}) => {
        const form = new FormData();
        form.append('file', file);
        return apiCore.post('/restore', form, options);
    },

    /**
     * Disk usage snapshot for configured container mount points.
     * @param {Object} options - Request options
     * @returns {Promise<Object>} { mounts: [{ path, exists, total_bytes, free_bytes, percent_used }] }
     */
    getDiskUsage: (options = {}) => {
        return apiCore.get('/system/disk', {
            useCache: true,
            cacheTTL: 60 * 1000, // 1 minute cache — cheap call but no point hammering
            ...options,
        });
    },

    /**
     * List directory contents
     * @param {string} path - Directory path to list
     * @param {Object} options - Request options
     * @returns {Promise<Object>} Directory listing
     */
    listDirectory: (path, options = {}) => {
        return apiCore.get(`/directory?path=${encodeURIComponent(path)}`, {
            useCache: true,
            cacheTTL: 5 * 60 * 1000, // 5 minutes cache for directories
            ...options,
        });
    },

    /**
     * List filesystem roots the directory picker is permitted to browse.
     * @param {Object} options - Request options
     * @returns {Promise<Object>} { roots: string[] }
     */
    listAllowedRoots: (options = {}) => {
        return apiCore.get('/allowed-roots', {
            useCache: true,
            cacheTTL: 5 * 60 * 1000,
            ...options,
        });
    },

    /**
     * Test endpoint for API validation
     * @param {Object} testData - Test data to send
     * @param {Object} options - Request options
     * @returns {Promise<Object>} Test response
     */
    test: (testData = {}, options = {}) => {
        return apiCore.post(
            '/test',
            {
                message: 'test',
                data: null,
                ...testData,
            },
            options
        );
    },

    /**
     * Create directory
     * @param {string} path - Directory path to create
     * @param {Object} options - Request options
     * @returns {Promise<Object>} Creation response
     */
    createDirectory: (path, options = {}) => {
        return apiCore.post('/folder', { path }, options);
    },

    /**
     * Database statistics — per-table row counts plus page/freelist info
     * and the schema_migrations log.
     * @param {Object} options - Request options
     * @returns {Promise<Object>} { tables, page_size, page_count, freelist_count, total_bytes, free_bytes, file_bytes, schema_migrations }
     */
    getDbStats: (options = {}) => {
        return apiCore.get('/system/db-stats', { ...options });
    },

    /**
     * Run SQLite VACUUM to reclaim freed space.
     * @param {Object} options - Request options
     * @returns {Promise<Object>} { bytes_before, bytes_after, bytes_reclaimed, duration_ms }
     */
    vacuumDb: (options = {}) => {
        return apiCore.post('/system/db/vacuum', {}, options);
    },

    /**
     * Wipe poster_cache for a full rescan on the next poster_renamerr run.
     * @param {Object} options - Request options
     * @returns {Promise<Object>} { deleted }
     */
    clearPosterCache: (options = {}) => {
        return apiCore.post('/system/db/poster-cache/clear', {}, options);
    },

    /**
     * Reset poster-match coverage to all-missing (Unmatched page reset).
     * Clears matched flag + match metadata for media + collections, preserving
     * ignored/locked rows; the next poster_renamerr run re-matches.
     * @returns {Promise<Object>} { reset, media, collections }
     */
    resetPosterMatches: async (options = {}) => {
        const res = await apiCore.post('/system/db/poster-matches/reset', {}, options);
        // The Unmatched poster details + stats are now stale.
        apiCore.clearCache('/posters/unmatched/details');
        apiCore.clearCache('/posters/unmatched/stats');
        return res;
    },

    /**
     * Reset additional-artwork coverage to all-missing (Unmatched page reset),
     * preserving the per-type "not needed" (ignored) flags. The next
     * asset_renamerr run repopulates coverage.
     * @returns {Promise<Object>} { deleted }
     */
    resetArtworkMatches: async (options = {}) => {
        const res = await apiCore.post('/system/db/artwork-matches/reset', {}, options);
        apiCore.clearCache('/posters/unmatched/artwork');
        return res;
    },

    /**
     * Recent instance health snapshots (Plex / Radarr / Sonarr / Lidarr probes).
     * @param {Object} options - Request options
     * @param {number} options.limit - Max snapshots to return (default 200)
     * @param {string} options.instance - Optional instance_name filter
     * @returns {Promise<Object>} { snapshots: [{ snapshot_at, service, instance_name, status, response_time_ms, error }] }
     */
    getHealthSnapshots: (options = {}) => {
        const params = new URLSearchParams();
        if (options.limit != null) params.set('limit', options.limit);
        if (options.instance) params.set('instance', options.instance);
        const qs = params.toString();
        const url = qs ? `/system/health/snapshots?${qs}` : '/system/health/snapshots';
        return apiCore.get(url, {
            useCache: true,
            cacheTTL: 30 * 1000,
            ...options,
        });
    },
};
