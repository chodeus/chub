/** System API: version, directory browsing, backups and DB maintenance. */

import { apiCore } from './core.js';
import { downloadBlob } from '../download.js';

export const systemAPI = {
    /** Application version. */
    getVersion: (options = {}) => {
        return apiCore.get('/version', {
            useCache: true,
            cacheTTL: 60 * 60 * 1000, // 1 hour cache for version
            ...options,
        });
    },

    /** On-demand update check against the remote release manifest. */
    checkForUpdate: (options = {}) => {
        return apiCore.get('/version/check', { ...options });
    },

    /** Saved config+db backups in the backups directory. */
    listBackups: (options = {}) => {
        return apiCore.get('/backups', { ...options });
    },

    /** Create a backup and download the zip. Fetches with the auth header, or a
     *  401 body would be saved as the file. */
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

    /** Restore config from an uploaded backup zip (multipart). */
    restoreBackup: (file, options = {}) => {
        const form = new FormData();
        form.append('file', file);
        return apiCore.post('/restore', form, options);
    },

    /** Disk usage for the configured container mount points. */
    getDiskUsage: (options = {}) => {
        return apiCore.get('/system/disk', {
            useCache: true,
            cacheTTL: 60 * 1000, // 1 minute cache — cheap call but no point hammering
            ...options,
        });
    },

    /** List directory contents. */
    listDirectory: (path, options = {}) => {
        return apiCore.get(`/directory?path=${encodeURIComponent(path)}`, {
            useCache: true,
            cacheTTL: 5 * 60 * 1000, // 5 minutes cache for directories
            ...options,
        });
    },

    /** Filesystem roots the directory picker is permitted to browse. */
    listAllowedRoots: (options = {}) => {
        return apiCore.get('/allowed-roots', {
            useCache: true,
            cacheTTL: 5 * 60 * 1000,
            ...options,
        });
    },

    /** Test endpoint for API validation. */
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

    /** Create a directory. */
    createDirectory: (path, options = {}) => {
        return apiCore.post('/folder', { path }, options);
    },

    /** Per-table row counts, page/freelist info and the schema_migrations log. */
    getDbStats: (options = {}) => {
        return apiCore.get('/system/db-stats', { ...options });
    },

    /** Run SQLite VACUUM to reclaim freed space. */
    vacuumDb: (options = {}) => {
        return apiCore.post('/system/db/vacuum', {}, options);
    },

    /** Wipe poster_cache so the next poster_renamerr run rescans in full. */
    clearPosterCache: (options = {}) => {
        return apiCore.post('/system/db/poster-cache/clear', {}, options);
    },

    /** Reset poster-match coverage to all-missing, PRESERVING ignored/locked rows.
     *  The next poster_renamerr run re-matches. */
    resetPosterMatches: async (options = {}) => {
        const res = await apiCore.post('/system/db/poster-matches/reset', {}, options);
        // The Unmatched poster details + stats are now stale.
        apiCore.clearCache('/posters/unmatched/details');
        apiCore.clearCache('/posters/unmatched/stats');
        return res;
    },

    /** Reset artwork coverage to all-missing, PRESERVING the per-type "not needed"
     *  flags. The next asset_renamerr run repopulates it. */
    resetArtworkMatches: async (options = {}) => {
        const res = await apiCore.post('/system/db/artwork-matches/reset', {}, options);
        apiCore.clearCache('/posters/unmatched/artwork');
        return res;
    },

    /** Recent instance health snapshots (Plex / Radarr / Sonarr / Lidarr probes). */
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
