/**
 * Shared GDrive preset helpers
 *
 * Lifted out of PresetsField so the single-select preset dropdown and the
 * bulk preset picker fetch/normalize the catalogue identically (no drift).
 */

import { apiCore } from './api/core.js';

// Remote fallback used when the bundled /api/gdrive-presets endpoint is
// unreachable (e.g. an old image is still running after a frontend deploy).
// Keeps the picker populated instead of silently empty.
export const GDRIVE_PRESETS_FALLBACK_URL =
    'https://raw.githubusercontent.com/Drazzilb08/daps-gdrive-presets/CL2K/presets.json';

const EXTERNAL_FETCH_TIMEOUT_MS = 15_000;

// Presets ship with a bare curator name + a style tag; the UI shows the style
// as a prefix ("CL2K Solen") so the same curator across styles stays distinct.
export const prefixGdriveNames = arr =>
    (Array.isArray(arr) ? arr : []).map(p => {
        if (!p || !p.style || !p.name) return p;
        const prefix = `${p.style} `;
        if (p.name.startsWith(prefix)) return p;
        return { ...p, name: `${prefix}${p.name}` };
    });

export const normalizeGdrivePayload = (payload, isInternal) => {
    const data = isInternal ? payload?.data : payload;
    const arr = Array.isArray(data)
        ? data
        : Object.entries(data || {}).map(([name, v]) =>
              typeof v === 'object' ? { name, ...v } : { name, id: v }
          );
    return prefixGdriveNames(arr);
};

const tryFetch = async (url, internal) => {
    if (internal) {
        // apiCore prefixes /api itself, so strip it from the URL.
        const path = url.replace(/^\/api/, '');
        const payload = await apiCore.get(path, { useCache: false });
        return normalizeGdrivePayload(payload, true);
    }
    // Mirrors cl2k_maker.js: aborts a stalled external request so failure handling can continue.
    const resp = await fetch(url, { signal: AbortSignal.timeout(EXTERNAL_FETCH_TIMEOUT_MS) });
    if (!resp.ok) throw new Error(`HTTP ${resp.status} from ${url}`);
    const payload = await resp.json();
    return normalizeGdrivePayload(payload, false);
};

/**
 * Fetch GDrive presets from the given URL, falling back to the upstream
 * Drazzilb08 JSON if the primary URL fails or returns an empty list (e.g. the
 * backend image is stale and the new /api/gdrive-presets route 404s).
 *
 * @param {string} presetUrl - Primary preset URL ('/api/...' = internal).
 * @returns {Promise<Array>} Normalized, style-prefixed preset list.
 */
export const fetchGdrivePresets = async presetUrl => {
    // A non-string would throw on startsWith before the try below, so the fallback
    // this function exists for could never run.
    const url =
        typeof presetUrl === 'string' && presetUrl ? presetUrl : GDRIVE_PRESETS_FALLBACK_URL;
    const isInternal = url.startsWith('/api/');
    let arr = [];
    try {
        arr = await tryFetch(url, isInternal);
    } catch (err) {
        console.warn(`[gdrivePresets] primary preset fetch failed (${url}):`, err);
    }

    if ((!Array.isArray(arr) || arr.length === 0) && url !== GDRIVE_PRESETS_FALLBACK_URL) {
        try {
            console.warn('[gdrivePresets] falling back to upstream preset URL');
            arr = await tryFetch(GDRIVE_PRESETS_FALLBACK_URL, false);
        } catch (err) {
            console.error('[gdrivePresets] upstream fallback also failed:', err);
            arr = [];
        }
    }

    return Array.isArray(arr) ? arr : [];
};
