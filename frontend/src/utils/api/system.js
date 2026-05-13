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
