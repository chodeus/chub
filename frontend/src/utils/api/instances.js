/** Instances API: external service config, connection tests and health. */

import { apiCore } from './core.js';

export const instancesAPI = {
    /** All configured instances, optionally filtered by `options.type`. */
    fetchInstances: async (options = {}) => {
        const { type, ...requestOptions } = options;
        const params = type ? `?type=${type}` : '';

        const response = await apiCore.get(`/instances${params}`, {
            useCache: true,
            cacheTTL: 5 * 60 * 1000, // 5 minutes cache
            ...requestOptions,
        });

        // Extract data from CHUB API response format
        return response.data || response;
    },

    /** Create an instance from { name, type, url, apiKey, settings }. */
    createInstance: instanceData => {
        return apiCore.post('/instances', instanceData);
    },

    /** Update an instance's configuration. */
    updateInstance: (instanceId, instanceData) => {
        return apiCore.put(`/instances/${instanceId}`, instanceData);
    },

    /** Delete an instance. Takes the exact stored name, not a humanized label. */
    deleteInstance: (instanceId, serviceType) => {
        return apiCore.delete(`/instances/${instanceId}?service=${serviceType}`);
    },

    /** Test a configuration without saving it. */
    testInstanceConfig: instanceData => {
        return apiCore.post('/instances/test', instanceData);
    },

    /** Health for one instance, or all when `instanceId` is null. */
    fetchHealthStatus: (instanceId = null, options = {}) => {
        const url = instanceId ? `/instances/${instanceId}/health` : '/instances/health';
        return apiCore.get(url, {
            useCache: false, // Health should be real-time
            ...options,
        });
    },

    /** Instance statistics; `options.period` is 24h, 7d or 30d. */
    fetchStatistics: (instanceId, options = {}) => {
        const params = new URLSearchParams(options);
        const url = params.toString()
            ? `/instances/${instanceId}/stats?${params}`
            : `/instances/${instanceId}/stats`;

        return apiCore.get(url, {
            useCache: true,
            cacheTTL: 5 * 60 * 1000,
        });
    },

    /** The supported instance types. */
    fetchSupportedTypes: (options = {}) => {
        return apiCore.get('/instances/types', {
            useCache: true,
            cacheTTL: 30 * 60 * 1000, // 30 minutes cache
            ...options,
        });
    },

    /** Config schema for one instance type. */
    fetchTypeSchema: (instanceType, options = {}) => {
        return apiCore.get(`/instances/types/${instanceType}/schema`, {
            useCache: true,
            cacheTTL: 30 * 60 * 1000,
            ...options,
        });
    },

    /** Enable or disable an instance. */
    toggleInstance: (instanceId, enabled) => {
        return apiCore.patch(`/instances/${instanceId}`, { enabled });
    },

    /** Refresh one instance's cached data. */
    refreshInstance: instanceId => {
        return apiCore.post(`/instances/${instanceId}/refresh`);
    },

    /** Instance logs; `options` accepts limit, level and since. */
    fetchInstanceLogs: (instanceId, options = {}) => {
        const params = new URLSearchParams();

        Object.entries(options).forEach(([key, value]) => {
            if (value !== undefined && value !== null) {
                if (value instanceof Date) {
                    params.set(key, value.toISOString());
                } else {
                    params.set(key, value.toString());
                }
            }
        });

        const url = params.toString()
            ? `/instances/${instanceId}/logs?${params}`
            : `/instances/${instanceId}/logs`;

        return apiCore.get(url, {
            useCache: false,
        });
    },

    /** Queue a data sync for one instance. */
    syncInstance: (instanceId, options = {}) => {
        return apiCore.post(`/instances/${instanceId}/sync`, options);
    },

    /** Plex libraries for one instance. */
    fetchPlexLibraries: (instanceName, options = {}) => {
        // A name may hold `/`, `?` or `#`, which would re-shape the URL before the
        // backend ever validates it.
        return apiCore.get(`/plex/${encodeURIComponent(instanceName)}/libraries`, {
            useCache: true,
            cacheTTL: 10 * 60 * 1000, // 10 minutes cache for library data
            ...options,
        });
    },

    /** Catalogued libraries for every Plex instance, keyed by instance name. */
    fetchPlexCatalog: (options = {}) => {
        return apiCore.get('/plex/libraries', {
            useCache: true,
            cacheTTL: 10 * 60 * 1000,
            ...options,
        });
    },

    /** Replace a Plex instance's opted-in library allow-list. Omitted libraries are
     *  hidden everywhere, and the backend purges their cached rows. */
    updateInstanceLibraries: async (instanceName, enabledLibraries) => {
        // Encode once and reuse: the cache key below must match the URL fetched.
        const encodedName = encodeURIComponent(instanceName);
        const result = await apiCore.patch(`/plex/${encodedName}/libraries`, {
            enabled_libraries: enabledLibraries,
        });
        // The catalog + per-instance library lists are cached under /plex/*,
        // which the instance-path mutation clear doesn't touch — drop them so
        // every picker and the opt-in UI refetch the new enabled state.
        apiCore.clearCache('/plex/libraries');
        apiCore.clearCache(`/plex/${encodedName}/libraries`);
        return result;
    },
};
