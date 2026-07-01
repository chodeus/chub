/**
 * CHUB Media API Module
 *
 * Handles media library management operations:
 * - Media search and filtering
 * - Media metadata management
 * - Library statistics
 * - Media processing operations
 */

import { apiCore } from './core.js';
import { streamTokenParam } from './streamAuth.js';

/**
 * Media API client for library management
 */
export const mediaAPI = {
    /**
     * Build an authenticated URL for a media item's poster image. Carries a
     * short-lived, scope-limited stream token (not the session JWT) as a query
     * param, since `<img src>` can't send the Authorization header.
     *
     * @param {number|string} mediaId
     * @returns {string|null} URL, or null if mediaId is missing.
     */
    getPosterUrl: mediaId => {
        if (mediaId === undefined || mediaId === null || mediaId === '') {
            return null;
        }
        const params = new URLSearchParams();
        const token = streamTokenParam();
        if (token) params.set('token', token);
        const qs = params.toString();
        return qs ? `/api/media/${mediaId}/poster?${qs}` : `/api/media/${mediaId}/poster`;
    },

    /**
     * Search media library
     * @param {Object} searchParams - Search parameters
     * @param {string} searchParams.query - Search query string
     * @param {string} searchParams.type - Media type filter (movie, tv, all)
     * @param {Array} searchParams.genres - Genre filters
     * @param {Object} searchParams.year - Year range {min, max}
     * @param {Object} searchParams.rating - Rating range {min, max}
     * @param {string} searchParams.sort - Sort field
     * @param {string} searchParams.order - Sort order (asc, desc)
     * @param {number} searchParams.limit - Results limit
     * @param {number} searchParams.offset - Results offset
     * @returns {Promise<Object>} Search results with pagination
     */
    searchMedia: (searchParams = {}) => {
        const params = new URLSearchParams();

        Object.entries(searchParams).forEach(([key, value]) => {
            if (value !== undefined && value !== null) {
                if (typeof value === 'object' && !Array.isArray(value)) {
                    // Handle range objects
                    if (value.min !== undefined) params.set(`${key}_min`, value.min);
                    if (value.max !== undefined) params.set(`${key}_max`, value.max);
                } else if (Array.isArray(value)) {
                    // Handle arrays
                    value.forEach(item => params.append(key, item));
                } else {
                    params.set(key, value.toString());
                }
            }
        });

        return apiCore.get(`/media/search?${params}`, {
            useCache: true,
            cacheTTL: 2 * 60 * 1000, // 2 minutes cache for search
        });
    },

    /**
     * Fetch specific media item
     * @param {string} mediaId - Media identifier
     * @param {Object} options - Request options
     * @returns {Promise<Object>} Media item details
     */
    fetchMediaItem: (mediaId, options = {}) => {
        return apiCore.get(`/media/${mediaId}`, {
            useCache: true,
            cacheTTL: 10 * 60 * 1000, // 10 minutes cache
            ...options,
        });
    },

    /**
     * Update media item metadata
     * @param {string} mediaId - Media identifier
     * @param {Object} metadata - Updated metadata
     * @returns {Promise<Object>} Update response
     */
    updateMediaMetadata: (mediaId, metadata) => {
        return apiCore.put(`/media/${mediaId}/metadata`, metadata);
    },

    /**
     * Fetch the metadata-edit audit trail for a single media item.
     * @param {string|number} mediaId - Media identifier
     * @param {number} limit - Max entries (default 50, server caps at 500)
     * @returns {Promise<Object>} { history: [{ id, media_id, field, old_value, new_value, edited_by, edited_at }] }
     */
    fetchMediaHistory: (mediaId, limit = 50) => {
        return apiCore.get(`/media/${mediaId}/history?limit=${limit}`, {
            useCache: false,
        });
    },

    /**
     * Delete media item
     * @param {string} mediaId - Media identifier
     * @param {Object} options - Deletion options
     * @param {boolean} options.deleteFiles - Also delete files from disk
     * @returns {Promise<Object>} Deletion response
     */
    deleteMediaItem: (mediaId, options = {}) => {
        return apiCore.delete(`/media/${mediaId}`, {
            body: JSON.stringify(options),
        });
    },

    /**
     * Bulk-delete media cache items (optionally from their *arr instance + disk).
     * @param {number[]} ids - Media IDs to delete
     * @param {{deleteFiles?: boolean, addImportExclusion?: boolean}} [options]
     * @returns {Promise<Object>} { removed, failed }
     */
    bulkDeleteMedia: (ids, options = {}) => {
        return apiCore.post('/media/bulk-delete', { ids, ...options });
    },

    /**
     * Fetch media library statistics
     * @param {Object} options - Statistics options
     * @param {string} options.type - Media type filter
     * @param {string} options.period - Time period for activity stats
     * @returns {Promise<Object>} Library statistics
     */
    fetchStatistics: (options = {}) => {
        const params = new URLSearchParams(options);
        const url = params.toString() ? `/media/stats?${params}` : '/media/stats';

        return apiCore.get(url, {
            useCache: true,
            cacheTTL: 5 * 60 * 1000, // 5 minutes cache
        });
    },

    /**
     * Fetch detailed media statistics with breakdowns by multiple dimensions.
     */
    fetchDetailedStatistics: (options = {}) => {
        const params = new URLSearchParams(options);
        const url = params.toString() ? `/media/stats/detailed?${params}` : '/media/stats/detailed';

        return apiCore.get(url, {
            useCache: true,
            cacheTTL: 5 * 60 * 1000,
        });
    },

    /**
     * Refresh media library
     * @param {Object} options - Refresh options
     * @param {string} options.path - Specific path to refresh
     * @param {boolean} options.deep - Deep scan for changes
     * @returns {Promise<Object>} Refresh job information
     */
    refreshLibrary: (options = {}) => {
        return apiCore.post('/media/refresh', options);
    },

    /**
     * Fetch media genres
     * @param {Object} options - Request options
     * @param {string} options.type - Media type filter
     * @returns {Promise<Array>} List of genres
     */
    fetchGenres: (options = {}) => {
        const params = new URLSearchParams(options);
        const url = params.toString() ? `/media/genres?${params}` : '/media/genres';

        return apiCore.get(url, {
            useCache: true,
            cacheTTL: 30 * 60 * 1000, // 30 minutes cache
        });
    },

    /**
     * Fetch media collections
     * @param {Object} options - Request options
     * @returns {Promise<Array>} List of collections
     */
    fetchCollections: (options = {}) => {
        return apiCore.get('/media/collections', {
            useCache: true,
            cacheTTL: 10 * 60 * 1000,
            ...options,
        });
    },

    /**
     * Create media collection
     * @param {Object} collectionData - Collection data
     * @param {string} collectionData.name - Collection name
     * @param {string} collectionData.description - Collection description
     * @param {Array} collectionData.mediaIds - Media items in collection
     * @returns {Promise<Object>} Created collection
     */
    createCollection: collectionData => {
        return apiCore.post('/media/collections', collectionData);
    },

    /**
     * Update media collection
     * @param {string} collectionId - Collection identifier
     * @param {Object} collectionData - Updated collection data
     * @returns {Promise<Object>} Updated collection
     */
    updateCollection: (collectionId, collectionData) => {
        return apiCore.put(`/media/collections/${collectionId}`, collectionData);
    },

    /**
     * Delete media collection
     * @param {string} collectionId - Collection identifier
     * @returns {Promise<Object>} Deletion response
     */
    deleteCollection: collectionId => {
        return apiCore.delete(`/media/collections/${collectionId}`);
    },

    /**
     * Fetch media duplicates and folder collisions
     * @param {Object} options - Detection options
     * @param {string} options.type - Media type filter
     * @returns {Promise<Object>} { duplicates, folder_collisions, total, total_collisions }
     */
    fetchDuplicates: (options = {}) => {
        const params = new URLSearchParams(options);
        const url = params.toString() ? `/media/duplicates?${params}` : '/media/duplicates';

        return apiCore.get(url, {
            useCache: true,
            cacheTTL: 10 * 60 * 1000,
        });
    },

    /**
     * Resolve media duplicates
     * @param {string} duplicateGroupId - Duplicate group identifier
     * @param {Object} resolution - Resolution action
     * @param {string} resolution.keepId - Media ID to keep
     * @param {Array} resolution.removeIds - Media IDs to remove
     * @param {boolean} resolution.deleteFiles - Delete files from disk
     * @returns {Promise<Object>} Resolution response
     */
    resolveDuplicates: async (duplicateGroupId, resolution) => {
        const res = await apiCore.post(`/media/duplicates/${duplicateGroupId}/resolve`, resolution);
        // The nested .../resolve path's auto-invalidation can't reach the
        // /media/duplicates list cache key — clear it so the group doesn't linger.
        apiCore.clearCache('/media/duplicates');
        return res;
    },

    /**
     * Export media data
     * @param {Object} options - Export options
     * @param {string} options.format - Export format (json, csv, xml)
     * @param {Array} options.fields - Fields to include
     * @param {Object} options.filters - Export filters
     * @returns {Promise<Object>} Export data or job information
     */
    exportMedia: (options = {}) => {
        return apiCore.post('/media/export', options);
    },

    fetchDuplicateMembers: ids => apiCore.post('/media/duplicates/members', { ids }),

    fetchOrphaned: () => apiCore.get('/media/orphaned', { useCache: false }),

    purgeOrphaned: ids => apiCore.post('/media/orphaned/purge', { ids }),

    fetchIncompleteMetadata: ({
        fields = 'tmdb_id,tvdb_id,imdb_id,year',
        limit = 500,
        offset = 0,
    } = {}) =>
        apiCore.get(
            `/media/incomplete-metadata?fields=${encodeURIComponent(fields)}&limit=${limit}&offset=${offset}`,
            { useCache: false }
        ),
};
