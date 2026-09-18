/** Media API: library search, metadata, statistics and collections. */

import { apiCore } from './core.js';
import { streamTokenParam, streamAuthDisabled } from './streamAuth.js';

// 1x1 transparent GIF: shown while a token is pending so no token-less request 401s.
// useStreamToken re-renders with the real URL once it lands.
const BLANK_IMAGE = 'data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==';

export const mediaAPI = {
    /** Poster URL carrying the short-lived, scope-limited stream token — never the
     *  session JWT, since `<img src>` cannot send an Authorization header. */
    getPosterUrl: mediaId => {
        if (mediaId === undefined || mediaId === null || mediaId === '') {
            return null;
        }
        const token = streamTokenParam();
        // No token yet: only show a blank placeholder while a token is genuinely
        // pending (auth on). When auth is not configured the token is empty for
        // good and the route is open, so fire a token-less URL — otherwise
        // posters render solid blank forever.
        if (!token && !streamAuthDisabled()) return BLANK_IMAGE;
        const q = token ? `?token=${encodeURIComponent(token)}` : '';
        return `/api/media/${mediaId}/poster${q}`;
    },

    /** Search the library. Range objects become `{key}_min`/`{key}_max`, arrays repeat the key. */
    searchMedia: (searchParams = {}) => {
        const params = new URLSearchParams();

        Object.entries(searchParams).forEach(([key, value]) => {
            if (value !== undefined && value !== null) {
                if (typeof value === 'object' && !Array.isArray(value)) {
                    if (value.min !== undefined) params.set(`${key}_min`, value.min);
                    if (value.max !== undefined) params.set(`${key}_max`, value.max);
                } else if (Array.isArray(value)) {
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

    /** One media item's details. */
    fetchMediaItem: (mediaId, options = {}) => {
        return apiCore.get(`/media/${mediaId}`, {
            useCache: true,
            cacheTTL: 10 * 60 * 1000, // 10 minutes cache
            ...options,
        });
    },

    /** Update a media item's metadata. */
    updateMediaMetadata: (mediaId, metadata) => {
        return apiCore.put(`/media/${mediaId}/metadata`, metadata);
    },

    /** Metadata-edit audit trail for one item; the server caps `limit` at 500. */
    fetchMediaHistory: (mediaId, limit = 50) => {
        return apiCore.get(`/media/${mediaId}/history?limit=${limit}`, {
            useCache: false,
        });
    },

    /** Delete a media item. `options.deleteFiles` also removes it from disk. */
    deleteMediaItem: (mediaId, options = {}) => {
        return apiCore.delete(`/media/${mediaId}`, {
            body: JSON.stringify(options),
        });
    },

    /** Bulk-delete cache items. Each is removed from its *arr regardless; `deleteFiles`
     *  additionally deletes the files, and `addImportExclusion` blocks re-import. */
    bulkDeleteMedia: (ids, options = {}) => {
        return apiCore.post('/media/bulk-delete', { ids, ...options });
    },

    /** Library statistics. */
    fetchStatistics: (options = {}) => {
        const params = new URLSearchParams(options);
        const url = params.toString() ? `/media/stats?${params}` : '/media/stats';

        return apiCore.get(url, {
            useCache: true,
            cacheTTL: 5 * 60 * 1000, // 5 minutes cache
        });
    },

    /** Statistics broken down by multiple dimensions. */
    fetchDetailedStatistics: (options = {}) => {
        const params = new URLSearchParams(options);
        const url = params.toString() ? `/media/stats/detailed?${params}` : '/media/stats/detailed';

        return apiCore.get(url, {
            useCache: true,
            cacheTTL: 5 * 60 * 1000,
        });
    },

    /** Queue a cache refresh. The backend drops unknown keys, so nothing here targets a
     *  subset — it always refreshes everything. */
    refreshLibrary: (options = {}) => {
        return apiCore.post('/media/refresh', options);
    },

    /** Known genres, optionally filtered by media type. */
    fetchGenres: (options = {}) => {
        const params = new URLSearchParams(options);
        const url = params.toString() ? `/media/genres?${params}` : '/media/genres';

        return apiCore.get(url, {
            useCache: true,
            cacheTTL: 30 * 60 * 1000, // 30 minutes cache
        });
    },

    /** All media collections. */
    fetchCollections: (options = {}) => {
        return apiCore.get('/media/collections', {
            useCache: true,
            cacheTTL: 10 * 60 * 1000,
            ...options,
        });
    },

    /** Create a collection from { name, description, mediaIds }. */
    createCollection: collectionData => {
        return apiCore.post('/media/collections', collectionData);
    },

    /** Update a collection. */
    updateCollection: (collectionId, collectionData) => {
        return apiCore.put(`/media/collections/${collectionId}`, collectionData);
    },

    /** Delete a collection. */
    deleteCollection: collectionId => {
        return apiCore.delete(`/media/collections/${collectionId}`);
    },

    /** Duplicate groups and folder collisions. */
    fetchDuplicates: (options = {}) => {
        const params = new URLSearchParams(options);
        const url = params.toString() ? `/media/duplicates?${params}` : '/media/duplicates';

        return apiCore.get(url, {
            useCache: true,
            cacheTTL: 10 * 60 * 1000,
        });
    },

    /** Resolve a duplicate group from { keepId, removeIds, deleteFiles }. */
    resolveDuplicates: async (duplicateGroupId, resolution) => {
        const res = await apiCore.post(`/media/duplicates/${duplicateGroupId}/resolve`, resolution);
        // The nested .../resolve path's auto-invalidation can't reach the
        // /media/duplicates list cache key — clear it so the group doesn't linger.
        apiCore.clearCache('/media/duplicates');
        return res;
    },

    /** Export media data; `options.format` is json, csv or xml. */
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
