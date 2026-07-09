/**
 * CHUB Posters API Module
 *
 * Handles poster and artwork management operations:
 * - Poster search and discovery
 * - Poster download and management
 * - Artwork collection operations
 * - Poster quality and metadata
 */

import { apiCore } from './core.js';
import { streamTokenParam, streamAuthDisabled } from './streamAuth.js';

// 1x1 transparent GIF — returned by the token-gated image builders below when
// the stream token isn't ready yet, so no token-less request fires (which would
// 401). useStreamToken re-renders the grid with the real URL once it lands.
const BLANK_IMAGE = 'data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==';

/**
 * Posters API client for artwork management
 */
export const postersAPI = {
    /**
     * Download a poster file to the user's disk.
     *
     * The backend reads size/format/quality as query params and responds with
     * the binary image. apiCore is JSON-oriented and would just buffer those
     * bytes into memory, so we fetch directly here and trigger a real browser
     * download via an object URL. The auth header is attached so the backend
     * can't 401 (which would otherwise be saved as the file body).
     *
     * @param {string} posterId - Poster identifier
     * @param {Object} options - Download options
     * @param {number} [options.size] - Max dimension in px (omit for original)
     * @param {string} [options.format] - Target format: jpg, webp, png
     * @param {number} [options.quality] - Compression quality 1-100
     * @param {string} [options.filename] - Preferred download filename
     * @returns {Promise<void>}
     * @throws {Error} If the server returns a non-OK response
     */
    downloadPoster: async (posterId, options = {}) => {
        const params = new URLSearchParams();
        if (options.size) params.set('size', options.size);
        if (options.format) params.set('format', options.format);
        if (options.quality) params.set('quality', options.quality);
        const qs = params.toString();
        const url = `/api/posters/${posterId}/download${qs ? `?${qs}` : ''}`;

        const headers = {};
        try {
            const token = localStorage.getItem('chub-auth-token');
            if (token) {
                headers['Authorization'] = `Bearer ${token}`;
            }
        } catch {
            /* localStorage unavailable */
        }

        const res = await fetch(url, { method: 'POST', headers });
        if (!res.ok) {
            throw new Error(`Download failed with status ${res.status}`);
        }

        // Prefer the server's Content-Disposition filename, then a caller
        // hint, then a sensible default derived from id + chosen format.
        let fileName = options.filename || `poster_${posterId}`;
        const disposition = res.headers.get('content-disposition');
        const match = disposition && /filename="?([^"]+)"?/.exec(disposition);
        if (match) {
            fileName = match[1];
        } else if (!/\.[a-z0-9]+$/i.test(fileName)) {
            const ext = String(options.format || 'jpg')
                .toLowerCase()
                .replace('jpeg', 'jpg');
            fileName = `${fileName}.${ext}`;
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
     * Upload poster
     * @param {FormData|Object} posterData - Poster data
     * @param {Object} metadata - Poster metadata
     * @param {string} metadata.mediaId - Associated media ID
     * @param {string} metadata.type - Poster type
     * @param {string} metadata.title - Poster title
     * @returns {Promise<Object>} Upload response
     */
    uploadPoster: (posterData, metadata = {}) => {
        const formData = posterData instanceof FormData ? posterData : new FormData();

        if (!(posterData instanceof FormData)) {
            Object.entries(posterData).forEach(([key, value]) => {
                formData.append(key, value);
            });
        }

        // Add metadata
        Object.entries(metadata).forEach(([key, value]) => {
            formData.append(`metadata[${key}]`, value);
        });

        return apiCore.post('/posters/upload', formData, {
            headers: {
                // Remove content-type to let browser set multipart boundary
                'Content-Type': undefined,
            },
        });
    },

    /**
     * Delete poster
     * @param {string} posterId - Poster identifier
     * @param {Object} options - Deletion options
     * @param {boolean} options.deleteFile - Delete file from storage
     * @returns {Promise<Object>} Deletion response
     */
    deletePoster: (posterId, options = {}) => {
        return apiCore.delete(`/posters/${posterId}`, {
            body: JSON.stringify(options),
        });
    },

    /**
     * Fetch poster collections
     * @param {Object} options - Request options
     * @param {string} options.type - Collection type filter
     * @returns {Promise<Array>} List of poster collections
     */
    fetchCollections: (options = {}) => {
        const params = new URLSearchParams(options);
        const url = params.toString() ? `/posters/collections?${params}` : '/posters/collections';

        return apiCore.get(url, {
            useCache: true,
            cacheTTL: 10 * 60 * 1000,
        });
    },

    /**
     * Create poster collection
     * @param {Object} collectionData - Collection data
     * @param {string} collectionData.name - Collection name
     * @param {string} collectionData.description - Collection description
     * @param {string} collectionData.type - Collection type
     * @returns {Promise<Object>} Created collection
     */
    createCollection: collectionData => {
        return apiCore.post('/posters/collections', collectionData);
    },

    /**
     * Add poster to collection
     * @param {string} collectionId - Collection identifier
     * @param {string} posterId - Poster identifier
     * @param {Object} options - Addition options
     * @returns {Promise<Object>} Addition response
     */
    addToCollection: (collectionId, posterId, options = {}) => {
        return apiCore.post(`/posters/collections/${collectionId}/add`, {
            poster_id: posterId,
            ...options,
        });
    },

    /**
     * Remove poster from collection
     * @param {string} collectionId - Collection identifier
     * @param {string} posterId - Poster identifier
     * @returns {Promise<Object>} Removal response
     */
    removeFromCollection: (collectionId, posterId) => {
        return apiCore.delete(`/posters/collections/${collectionId}/remove/${posterId}`);
    },

    /**
     * Delete a whole poster collection (and its membership rows).
     * Underlying poster files are not touched.
     * @param {string|number} collectionId - Collection identifier
     * @returns {Promise<Object>} Deletion response
     */
    deleteCollection: collectionId => {
        return apiCore.delete(`/posters/collections/${collectionId}`);
    },

    /**
     * Posters whose `created_at` is at or after the given ISO cutoff.
     * @param {string} cutoff - ISO-8601 timestamp
     * @param {number} limit - Max rows (default 100)
     * @returns {Promise<Object>} { items, cutoff }
     */
    fetchPostersAddedSince: (cutoff, limit = 100) => {
        const params = new URLSearchParams({ cutoff, limit: String(limit) });
        return apiCore.get(`/posters/added-since?${params}`, {
            useCache: true,
            cacheTTL: 60 * 1000,
        });
    },

    /**
     * The posters CHUB most recently matched/applied to media, newest first
     * (genuine match recency, not cache-insertion order).
     * @param {number} limit - Max rows (default 50)
     * @returns {Promise<Object>} { items }
     */
    fetchRecentlyMatched: (limit = 50) => {
        const params = new URLSearchParams({ limit: String(limit) });
        return apiCore.get(`/posters/recently-matched?${params}`, {
            useCache: true,
            cacheTTL: 60 * 1000,
        });
    },

    /**
     * Matched media whose applied poster is of the given variant (e.g. CL2K).
     * @param {string} style - Poster variant
     * @param {{type?: string, limit?: number, offset?: number}} [opts]
     * @returns {Promise<Object>} { items, total, style, limit, offset }
     */
    fetchAppliedByStyle: (style, { type, limit = 50, offset = 0 } = {}) => {
        const params = new URLSearchParams({
            style,
            limit: String(limit),
            offset: String(offset),
        });
        if (type) params.set('type', type);
        return apiCore.get(`/posters/applied?${params}`, {
            useCache: true,
            cacheTTL: 60 * 1000,
        });
    },

    /**
     * Posters with recorded width below `min_width`. Run /backfill-dimensions
     * first to populate unset rows or results will be empty/incomplete.
     * @param {number} minWidth - Width threshold in pixels (default 1000)
     * @param {number} limit - Max rows (default 200)
     * @returns {Promise<Object>} { items, min_width }
     */
    fetchLowResolutionPosters: (minWidth = 1000, limit = 200) => {
        const params = new URLSearchParams({
            min_width: String(minWidth),
            limit: String(limit),
        });
        return apiCore.get(`/posters/low-resolution?${params}`, {
            useCache: true,
            cacheTTL: 60 * 1000,
        });
    },

    /**
     * Trigger backfill of width/height for poster_cache rows where dimensions
     * aren't yet recorded. Returns counts of populated/skipped.
     * @returns {Promise<Object>}
     */
    backfillPosterDimensions: () => {
        return apiCore.post('/posters/backfill-dimensions', {});
    },

    /**
     * Fetch poster statistics
     * @param {Object} options - Statistics options
     * @param {string} options.groupBy - Group by (type, source, quality)
     * @param {string} options.period - Time period
     * @returns {Promise<Object>} Poster statistics
     */
    fetchStatistics: (options = {}) => {
        const params = new URLSearchParams(options);
        const url = params.toString() ? `/posters/stats?${params}` : '/posters/stats';

        return apiCore.get(url, {
            useCache: true,
            cacheTTL: 5 * 60 * 1000,
        });
    },

    /**
     * Search Google Drive for posters
     * @param {Object} searchParams - GDrive search parameters
     * @param {string} searchParams.query - Search query
     * @param {string} searchParams.folder - Specific folder to search
     * @param {string} searchParams.mediaType - Media type filter
     * @returns {Promise<Object>} GDrive search results
     */
    searchGoogleDrive: (searchParams = {}) => {
        const params = new URLSearchParams(searchParams);
        return apiCore.get(`/posters/sources/gdrive/search?${params}`, {
            useCache: true,
            cacheTTL: 2 * 60 * 1000, // 2 minutes cache for GDrive
        });
    },

    /**
     * Delete a GDrive drive's local synced folder and purge its cached
     * poster rows. Backend only deletes a folder matching a currently
     * configured gdrive_list location.
     * @param {Object} options
     * @param {string} options.location - Local folder of the drive to remove
     * @returns {Promise<Object>} { folder_removed, deleted_rows, location }
     */
    deleteGdriveLocal: (options = {}) => {
        return apiCore.post('/posters/gdrive/delete-local', options);
    },

    /**
     * Auto-match posters to media
     * @param {Object} options - Matching options
     * @param {string} options.mediaId - Specific media ID (optional)
     * @param {string} options.source - Source to match from
     * @param {number} options.confidence - Minimum confidence threshold
     * @param {boolean} options.overwrite - Overwrite existing posters
     * @returns {Promise<Object>} Matching job information
     */
    autoMatchPosters: (options = {}) => {
        return apiCore.post('/posters/auto-match', options);
    },

    /**
     * Optimize poster storage
     * @param {Object} options - Optimization options
     * @param {Array} options.sizes - Target sizes to maintain
     * @param {string} options.format - Target format
     * @param {number} options.quality - Target quality
     * @returns {Promise<Object>} Optimization job information
     */
    optimizeStorage: (options = {}) => {
        return apiCore.post('/posters/optimize', options);
    },

    /**
     * Fetch list of poster files
     * @param {boolean} forceRefresh - Force refresh cache
     * @returns {Promise<Array>} Array of poster file names
     */
    fetchPosterFileList: (forceRefresh = false) => {
        return apiCore
            .get('/posters/list', {
                useCache: !forceRefresh,
                cacheTTL: 5 * 60 * 1000, // 5 minutes cache
            })
            .then(response => {
                // Extract files array from response
                if (response && response.data && Array.isArray(response.data.files)) {
                    return response.data.files;
                }
                return [];
            })
            .catch(error => {
                console.error('Failed to fetch poster file list:', error);
                return [];
            });
    },

    /**
     * Browse cached posters with optional filtering and pagination
     * @param {Object} options - Filter options
     * @param {string} [options.owner] - Filter by GDrive owner
     * @param {string} [options.type] - Filter by asset type (movie, show, season, collection)
     * @param {string} [options.query] - Search by title
     * @param {string} [options.style] - Filter by poster style (CL2K, MM2K, or 'other')
     * @param {number} [options.limit=60] - Results per page
     * @param {number} [options.offset=0] - Pagination offset
     * @returns {Promise<Object>} Paginated poster results with owners and styles
     */
    browsePosters: (options = {}) => {
        const params = new URLSearchParams();
        if (options.owner) params.set('owner', options.owner);
        if (options.type) params.set('type', options.type);
        if (options.query) params.set('query', options.query);
        if (options.style) params.set('style', options.style);
        if (options.image_type) params.set('image_type', options.image_type);
        if (options.limit) params.set('limit', options.limit);
        if (options.offset) params.set('offset', options.offset);
        const url = params.toString() ? `/posters/browse?${params}` : '/posters/browse';
        return apiCore.get(url);
    },

    /**
     * Get matched poster statistics
     * @returns {Promise<Object>} Matched poster statistics by owner
     */
    fetchMatchedStats: () => {
        return apiCore.get('/posters/matched/stats', {
            cacheTTL: 5 * 60 * 1000,
        });
    },

    /**
     * Get unmatched assets statistics
     * @returns {Promise<Object>} Unmatched assets summary
     */
    fetchUnmatchedStats: () => {
        return apiCore.get('/posters/unmatched/stats', {
            cacheTTL: 5 * 60 * 1000,
        });
    },

    /**
     * Get detailed unmatched assets with per-item data and external IDs
     * @returns {Promise<Object>} Unmatched items with summary and details
     */
    fetchUnmatchedDetails: () => {
        return apiCore.get('/posters/unmatched/details', {
            cacheTTL: 5 * 60 * 1000,
        });
    },

    /**
     * Additional-artwork coverage (logo/background/squareart) for the
     * Unmatched page's "Additional artwork" view.
     * @returns {Promise<Object>} { types: {logo,background,squareart}, summary }
     */
    fetchUnmatchedArtwork: () => {
        return apiCore.get('/posters/unmatched/artwork', {
            cacheTTL: 5 * 60 * 1000,
        });
    },

    /**
     * Toggle the per-(media, image_type) "not needed" ignore flag.
     * @param {number} id - media_cache id
     * @param {string} imageType - 'logo' | 'background' | 'squareart'
     * @param {Object} options - { kind: 'media'|'collection', ignored: bool }
     */
    ignoreArtwork: async (id, imageType, { kind = 'media', ignored = true } = {}) => {
        const params = new URLSearchParams({ kind, ignored: String(ignored) });
        const res = await apiCore.post(
            `/posters/match/${id}/artwork/${imageType}/ignore?${params}`,
            {}
        );
        apiCore.clearCache('/posters/unmatched/artwork');
        return res;
    },

    /**
     * Candidate artwork files for one (media, image_type) — the artwork
     * counterpart of fetchMatchCandidates, powering the manual artwork picker.
     * @param {number} id - media_cache or collections_cache id
     * @param {string} imageType - 'logo' | 'background' | 'squareart'
     * @param {Object} options - { kind: 'media'|'collection' }
     * @returns {Promise<Object>} { candidates: [...], media: {...} }
     */
    fetchArtworkCandidates: (id, imageType, { kind = 'media' } = {}) => {
        const params = new URLSearchParams({ kind });
        return apiCore.get(`/posters/match/${id}/artwork/${imageType}/candidates?${params}`, {
            useCache: false,
        });
    },

    /**
     * Manually apply a chosen artwork file to one (media, image_type) and lock
     * it so a re-run reuses it. The artwork counterpart of applyMatch.
     * @param {number} id - row id
     * @param {string} imageType - 'logo' | 'background' | 'squareart'
     * @param {number} posterId - poster_cache id of the chosen file
     * @param {Object} options - { kind: 'media'|'collection' }
     */
    applyArtwork: async (id, imageType, posterId, { kind = 'media' } = {}) => {
        const params = new URLSearchParams({ kind, poster_id: String(posterId) });
        const res = await apiCore.post(
            `/posters/match/${id}/artwork/${imageType}/apply?${params}`,
            {}
        );
        apiCore.clearCache('/posters/unmatched/artwork');
        return res;
    },

    /**
     * Unlock a manually-picked artwork so the matcher can re-resolve it.
     * The artwork counterpart of unlockMatch.
     * @param {number} id - row id
     * @param {string} imageType - 'logo' | 'background' | 'squareart'
     * @param {Object} options - { kind: 'media'|'collection' }
     */
    unlockArtwork: async (id, imageType, { kind = 'media' } = {}) => {
        const params = new URLSearchParams({ kind });
        const res = await apiCore.post(
            `/posters/match/${id}/artwork/${imageType}/unlock?${params}`,
            {}
        );
        apiCore.clearCache('/posters/unmatched/artwork');
        return res;
    },

    /**
     * Ignore (dismiss) or restore a media/collection row from the
     * Unmatched / Needs-Review tabs.
     * @param {number} id - media_cache or collections_cache row id
     * @param {Object} options - { kind: 'media'|'collection', ignored: boolean }
     */
    setMatchIgnored: async (id, { kind = 'media', ignored = true } = {}) => {
        const params = new URLSearchParams({ kind, ignored: String(ignored) });
        const res = await apiCore.post(`/posters/match/${id}/ignore?${params}`, {});
        // The Unmatched/Needs-Review/Ignored tabs all derive from this cached
        // GET — bust it so the follow-up refresh() reflects the change instead
        // of re-reading stale data.
        apiCore.clearCache('/posters/unmatched/details');
        return res;
    },

    /**
     * Approve a needs-review match, promoting it to the matched state.
     * @param {number} id - row id
     * @param {Object} options - { kind: 'media'|'collection' }
     */
    approveMatch: async (id, { kind = 'media' } = {}) => {
        const params = new URLSearchParams({ kind });
        const res = await apiCore.post(`/posters/match/${id}/approve?${params}`, {});
        apiCore.clearCache('/posters/unmatched/details');
        return res;
    },

    /**
     * Unlock a confirmed match, clearing the lock and re-opening it for review.
     * @param {number} id - row id
     * @param {Object} options - { kind: 'media'|'collection' }
     */
    unlockMatch: async (id, { kind = 'media' } = {}) => {
        const params = new URLSearchParams({ kind });
        const res = await apiCore.post(`/posters/match/${id}/unlock?${params}`, {});
        apiCore.clearCache('/posters/unmatched/details');
        return res;
    },

    /**
     * Candidate posters for a media/collection row (picker + why-no-match).
     * @param {number} id - row id
     * @param {Object} options - { kind: 'media'|'collection' }
     * @returns {Promise<Object>} { candidates: [...], media: {...} }
     */
    fetchMatchCandidates: (id, { kind = 'media' } = {}) => {
        const params = new URLSearchParams({ kind });
        return apiCore.get(`/posters/match/${id}/candidates?${params}`, {
            useCache: false,
        });
    },

    /**
     * Manually apply a chosen poster to a media/collection row.
     * @param {number} id - row id
     * @param {number} posterId - poster_cache id
     * @param {Object} options - { kind: 'media'|'collection' }
     */
    applyMatch: async (id, posterId, { kind = 'media' } = {}) => {
        const params = new URLSearchParams({ kind, poster_id: String(posterId) });
        const res = await apiCore.post(`/posters/match/${id}/apply?${params}`, {});
        apiCore.clearCache('/posters/unmatched/details');
        return res;
    },

    /**
     * Get GDrive synchronization statistics
     * @returns {Promise<Object>} GDrive sync statistics
     */
    fetchGDriveStats: () => {
        return apiCore.get('/posters/gdrive/stats', {
            cacheTTL: 2 * 60 * 1000,
        });
    },

    /**
     * Sync GDrive folders
     * @param {Array<string>} names - GDrive folder names to sync
     * @returns {Promise<Object>} Sync job IDs
     */
    syncGDriveFolders: names => {
        const params = names.map(n => `gdrive_names=${encodeURIComponent(n)}`).join('&');
        return apiCore.post(`/posters/gdrive/sync?${params}`);
    },

    /**
     * Analyze a directory for poster files
     * @param {string} location - Directory path to analyze
     * @returns {Promise<Object>} Directory analysis with file count and listing
     */
    analyzeDirectory: location => {
        const params = location ? `?location=${encodeURIComponent(location)}` : '';
        return apiCore.get(`/posters/analyze${params}`);
    },

    /**
     * Preview a poster file
     * @param {string} location - Base directory path
     * @param {string} path - File path (absolute or relative to location)
     * @returns {string} URL for poster preview image
     */
    getPreviewUrl: (location, path) => {
        const token = streamTokenParam();
        // Blank only while a token is pending (auth on); when auth is off the
        // token is permanently empty and the route is open — build it token-less.
        if (!token && !streamAuthDisabled()) return BLANK_IMAGE;
        const params = new URLSearchParams();
        if (location) params.set('location', location);
        if (path) params.set('path', path);
        if (token) params.set('token', token);
        return `/api/posters/preview?${params.toString()}`;
    },

    /**
     * Get authenticated thumbnail URL for a poster
     * @param {number|string} posterId - Poster ID
     * @param {number} [width=300] - Thumbnail width
     * @returns {string} Authenticated URL for poster thumbnail
     */
    getThumbnailUrl: (posterId, width = 300) => {
        const token = streamTokenParam();
        if (!token && !streamAuthDisabled()) return BLANK_IMAGE;
        const params = new URLSearchParams();
        params.set('width', width);
        if (token) params.set('token', token);
        return `/api/posters/${posterId}/thumbnail?${params.toString()}`;
    },

    // --- Poster Cleanarr / Plex Metadata scanning ------------------------

    /** List poster variants grouped by media item (Plex Metadata scan). */
    listPlexMetadataByMedia: (params = {}) => {
        const qs = new URLSearchParams();
        if (params.limit) qs.set('limit', params.limit);
        if (params.offset) qs.set('offset', params.offset);
        if (params.only_bloat) qs.set('only_bloat', 'true');
        if (params.force) qs.set('force', 'true');
        if (params.media_type && params.media_type !== 'all')
            qs.set('media_type', params.media_type);
        if (params.library_id) qs.set('library_id', params.library_id);
        if (params.variant_kind && params.variant_kind !== 'all')
            qs.set('variant_kind', params.variant_kind);
        // Cheap cache read now — the heavy walk runs in the background
        // `plex_metadata_scan` job, so the default request timeout is fine.
        // Returns `scan_required: true` with empty bundles when no scan is
        // cached; the caller enqueues one via `enqueuePlexMetadataScan`.
        return apiCore.get(`/posters/plex-metadata/by-media?${qs.toString()}`);
    },

    /** Enqueue a background Plex-metadata scan job (warms the bundle +
     *  transcoder cache off the event loop). Returns {job_id}; poll with
     *  `tailJobLog`, then re-fetch `listPlexMetadataByMedia`. */
    enqueuePlexMetadataScan: () => apiCore.post('/posters/plex-metadata/scan', {}),

    /** Flat list of bloat variants, largest first (cache-only read). */
    listPlexMetadataBloat: (params = {}) => {
        const qs = new URLSearchParams();
        if (params.limit) qs.set('limit', params.limit);
        if (params.offset) qs.set('offset', params.offset);
        return apiCore.get(`/posters/plex-metadata/bloat?${qs.toString()}`);
    },

    /** Enqueue a Poster Cleanarr cleanup job. */
    runPlexMetadataCleanup: body => apiCore.post('/posters/plex-metadata/cleanup', body || {}),

    /** Cached Kometa stale-duplicate + orphan scan (read-only, walk-free).
     *  Returns `scan_required: true` when unscanned; enqueue via
     *  `enqueueKometaAssetsScan`. */
    scanKometaAssets: () => apiCore.get('/posters/plex-metadata/kometa-assets-scan'),

    /** Enqueue a background Kometa stale/orphan scan job. Returns {job_id}. */
    enqueueKometaAssetsScan: () => apiCore.post('/posters/plex-metadata/kometa-scan', {}),

    /** Delete one variant file on disk. */
    deletePlexMetadataVariant: path =>
        apiCore.delete('/posters/plex-metadata/variant', {
            body: JSON.stringify({ path }),
            headers: { 'Content-Type': 'application/json' },
        }),

    /** Make a variant the active poster in Plex. */
    setPlexMetadataActive: (ratingKey, path) =>
        apiCore.post('/posters/plex-metadata/set-active', {
            rating_key: ratingKey,
            path,
        }),

    /** Authenticated URL for a variant image preview. */
    getPlexVariantUrl: path => {
        const token = streamTokenParam();
        if (!token && !streamAuthDisabled()) return BLANK_IMAGE;
        const params = new URLSearchParams();
        params.set('path', path);
        if (token) params.set('token', token);
        return `/api/posters/plex-metadata/variant-thumbnail?${params.toString()}`;
    },

    /** Poll a job's log file for incremental output. */
    tailJobLog: (jobId, offset = 0, maxBytes = 65536) => {
        const qs = new URLSearchParams();
        qs.set('offset', offset);
        qs.set('max_bytes', maxBytes);
        return apiCore.get(`/jobs/${jobId}/log-tail?${qs.toString()}`);
    },
};
