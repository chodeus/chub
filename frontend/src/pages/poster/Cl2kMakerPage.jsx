import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { cl2kMakerAPI } from '../../utils/api/cl2k_maker.js';
import { configAPI } from '../../utils/api/config.js';
import { postersAPI } from '../../utils/api/posters.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { Button, LoadingButton, PageHeader } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';

/**
 * CL2K Poster Maker.
 *
 * A 4-stage flow that turns a TMDB/TVDB/IMDB title into a DAPS-named CL2K
 * poster:
 *   1. Pick title — TMDB search, ID/URL paste, or a deep link from Unmatched
 *      Assets (?tmdb_id=&type=&title=).
 *   2. Source — where the artwork comes from: TMDB, fanart.tv, a manually
 *      cleaned backdrop, a finished poster used as-is, or a Drive .psd.
 *   3. Build + preview — art/logo picker, optional AI text-removal driven by a
 *      brushed mask, and a live preview.
 *   4. Output — generate (write + cache), export a layered .psd, download the
 *      backdrop for an external clean-up handoff, or browse history.
 *
 * Non-visual knobs (logo width, whiten, language, AI provider, output_dir) live
 * in Module Settings → CL2K Maker; this page reads them and links back to edit.
 */

const KIND_OPTIONS = [
    { value: 'movie', label: 'Movie' },
    { value: 'show', label: 'Show' },
    { value: 'collection', label: 'Collection' },
];

// CL2K bottom-banner labels (from the template). Empty = no banner / auto label.
const BAND_LABEL_OPTIONS = [
    { value: '', label: 'None' },
    { value: 'COMPLETE LIMITED SERIES', label: 'Complete Limited Series' },
    { value: 'SPECIALS', label: 'Specials' },
];

const SOURCE_TABS = [
    { key: 'tmdb', label: 'TMDB', icon: 'movie' },
    { key: 'fanart', label: 'fanart.tv', icon: 'palette' },
    { key: 'square', label: 'Square art', icon: 'crop_square' },
    { key: 'background', label: 'Background', icon: 'wallpaper' },
    { key: 'logo', label: 'Logo', icon: 'sell' },
    { key: 'upload-poster', label: 'Finished poster', icon: 'image' },
    { key: 'edit', label: 'Edit poster', icon: 'edit' },
];

// Map a deep-link / paste media type onto the kind strings the maker uses.
const normalizeKind = t => {
    const v = (t || '').toLowerCase();
    if (v === 'movie') return 'movie';
    if (v === 'collection') return 'collection';
    if (v === 'tv' || v === 'series' || v === 'show') return 'show';
    return 'movie';
};

// ─── ID / URL paste parsing ──────────────────────────────────────────────
// Accepts a bare id, or a TMDB / TVDB / IMDB url. Returns {source, id} where
// source is 'tmdb' (resolve not needed) or 'tvdb_id' / 'imdb_id' (needs resolve).
const parsePastedId = raw => {
    const s = (raw || '').trim();
    if (!s) return null;
    const imdb = s.match(/(tt\d{6,})/i);
    if (imdb) return { source: 'imdb_id', id: imdb[1] };
    const tmdbUrl = s.match(/themoviedb\.org\/(movie|tv|collection)\/(\d+)/i);
    if (tmdbUrl) return { source: 'tmdb', id: tmdbUrl[2], type: normalizeKind(tmdbUrl[1]) };
    const tvdbUrl = s.match(/thetvdb\.com\/.*?(\d{4,})/i);
    if (tvdbUrl) return { source: 'tvdb_id', id: tvdbUrl[1] };
    if (/^\d+$/.test(s)) return { source: 'tmdb', id: s };
    return null;
};

// ─── In-progress state persistence ───────────────────────────────────────────
// The page component unmounts on navigation, dropping all React state — so the
// poster you were building vanishes when you leave and come back. Persist the
// selected title + builder selections in sessionStorage (survives route changes,
// clears on tab close) so returning restores the work.
const SS_ITEM = 'cl2k:item';
const SS_SELKEY = 'cl2k:selKey';
const SS_BUILDER = 'cl2k:builder';

const ssRead = (key, fallback) => {
    try {
        const raw = sessionStorage.getItem(key);
        return raw == null ? fallback : JSON.parse(raw);
    } catch {
        return fallback;
    }
};
const ssWrite = (key, value) => {
    try {
        sessionStorage.setItem(key, JSON.stringify(value));
    } catch {
        /* sessionStorage unavailable (private mode / quota) — skip */
    }
};
const ssRemove = key => {
    try {
        sessionStorage.removeItem(key);
    } catch {
        /* noop */
    }
};

// Fetch TMDB external ids for a picked title and merge tvdb_id/imdb_id in where
// they're not already set, so filenames/matching are right without manual entry.
// Collections have no external ids; a lookup failure leaves the item untouched.
const withExternalIds = async base => {
    if (!base?.tmdb_id || base.kind === 'collection') return base;
    if (base.tvdb_id && base.imdb_id) return base;
    try {
        const resp = await cl2kMakerAPI.externalIds(base.tmdb_id, base.kind);
        const ext = resp?.data || {};
        return {
            ...base,
            tvdb_id: base.tvdb_id ?? (ext.tvdb_id || null),
            imdb_id: base.imdb_id ?? (ext.imdb_id || null),
        };
    } catch {
        return base;
    }
};

// ─── Logo placement geometry (mirrors renderer._place_logo) ──────────────────
// Same maths the backend uses to size + bottom-align the clear logo, so a CSS
// overlay drawn with /logo-processed bytes lands exactly where a render would.
// All px are on the locked 1000×1500 CL2K canvas.
const CL2K_CANVAS_W = 1000;
const CL2K_CANVAS_H = 1500;
const CL2K_LOGO_BASELINE = 1300; // geo.MAIN_LOGO_BOTTOM / COLLECTION_LOGO_BOTTOM
const CL2K_LOGO_WIDTH_MAX = 800; // geo.LOGO_WIDTH_MAX (hard cap)
const CL2K_LOGO_ZONE_TOP = 1100; // geo.LOGO_ZONE_TOP

// natW/natH = trimmed logo dims (from /logo-processed); maxWidth = cfg.logo_max_width.
// Returns the overlay box as percentages of the 2:3 preview, or null.
const logoBoxPct = ({ natW, natH, maxWidth, scale = 1, yOffset = 0 }) => {
    if (!natW || !natH) return null;
    const s = Math.max(0.25, Math.min(scale || 1, 3));
    const off = Math.max(-600, Math.min(Math.round(yOffset || 0), 200));
    let targetW = Math.min(maxWidth || 600, CL2K_LOGO_WIDTH_MAX);
    let targetH = Math.round((natH * targetW) / natW);
    const maxH = CL2K_LOGO_BASELINE - CL2K_LOGO_ZONE_TOP;
    if (targetH > maxH) {
        targetH = maxH;
        targetW = Math.round((natW * targetH) / natH);
    }
    // Scale the guide-fit box as a whole; keep it on the canvas (aspect kept) —
    // mirrors _place_logo so the overlay still lands pixel-exact.
    targetW = Math.round(targetW * s);
    targetH = Math.round(targetH * s);
    if (targetW > CL2K_CANVAS_W) {
        targetH = Math.round((targetH * CL2K_CANVAS_W) / targetW);
        targetW = CL2K_CANVAS_W;
    }
    if (targetH > CL2K_CANVAS_H) {
        targetW = Math.round((targetW * CL2K_CANVAS_H) / targetH);
        targetH = CL2K_CANVAS_H;
    }
    let top = CL2K_LOGO_BASELINE - targetH + off;
    top = Math.max(0, Math.min(top, CL2K_CANVAS_H - targetH));
    const left = CL2K_CANVAS_W / 2 - targetW / 2;
    return {
        left: (left / CL2K_CANVAS_W) * 100,
        top: (top / CL2K_CANVAS_H) * 100,
        width: (targetW / CL2K_CANVAS_W) * 100,
        height: (targetH / CL2K_CANVAS_H) * 100,
    };
};

// Live logo drawn over the logo-less preview base. Moves instantly with the
// size/position sliders — no server render per drag. `logo` = { dataUrl, width,
// height, maxWidth } from /logo-processed.
const LogoOverlay = ({ logo, scale, yOffset }) => {
    if (!logo?.dataUrl) return null;
    const box = logoBoxPct({
        natW: logo.width,
        natH: logo.height,
        maxWidth: logo.maxWidth,
        scale,
        yOffset,
    });
    if (!box) return null;
    return (
        <img
            src={logo.dataUrl}
            alt=""
            aria-hidden="true"
            style={{
                position: 'absolute',
                left: `${box.left}%`,
                top: `${box.top}%`,
                width: `${box.width}%`,
                height: `${box.height}%`,
                objectFit: 'fill',
                pointerEvents: 'none',
            }}
        />
    );
};

const Cl2kMakerPage = () => {
    const toast = useToast();
    const [searchParams] = useSearchParams();

    const [config, setConfig] = useState(null);
    // Drive-upload status (enabled + has a usable OAuth token) for the banner warning.
    const [uploadStatus, setUploadStatus] = useState(null);

    // Selected item: { tmdb_id, kind, title, year, tvdb_id, imdb_id } | null.
    // Seeded from an Unmatched-Assets deep link
    // (?tmdb_id=&type=&title=&year=&tvdb_id=&imdb_id=) when present; otherwise
    // restored from sessionStorage so an in-progress poster survives navigation.
    const [item, setItem] = useState(() => {
        const tmdbId = searchParams.get('tmdb_id');
        if (tmdbId) {
            // A fresh deep link is a new title — drop any stale builder snapshot.
            ssRemove(SS_BUILDER);
            return {
                tmdb_id: Number(tmdbId),
                kind: normalizeKind(searchParams.get('type')),
                title: searchParams.get('title') || '',
                year: searchParams.get('year') ? Number(searchParams.get('year')) : null,
                tvdb_id: searchParams.get('tvdb_id') ? Number(searchParams.get('tvdb_id')) : null,
                imdb_id: searchParams.get('imdb_id') || null,
            };
        }
        return ssRead(SS_ITEM, null);
    });

    // Bumped only when a NEW title is picked, so editing the ids in-place doesn't
    // remount the Builder (which would wipe panel state). Restored too, so the
    // Builder remounts with the same key and re-reads its saved selections.
    const [selectionKey, setSelectionKey] = useState(() => ssRead(SS_SELKEY, 0));
    const pickItem = useCallback(it => {
        ssRemove(SS_BUILDER); // a new title starts the builder fresh
        setItem(it);
        setSelectionKey(k => k + 1);
    }, []);

    // Persist the selected title + selection key across navigation.
    useEffect(() => {
        ssWrite(SS_ITEM, item);
    }, [item]);
    useEffect(() => {
        ssWrite(SS_SELKEY, selectionKey);
    }, [selectionKey]);

    const resetItem = useCallback(() => {
        ssRemove(SS_ITEM);
        ssRemove(SS_BUILDER);
        setItem(null);
    }, []);

    // Resolve a blank title from whatever id the item carries (TMDB → TVDB → IMDB)
    // so an id-only entry (paste / Edit IDs / deep link) shows the real name in the
    // header instead of "TMDB #…". Runs once per id-set and never overrides a title
    // the user has typed; a miss is harmless (the backend still backfills the
    // filename at save time).
    const titleProbe = useRef(null);
    // A newly picked title resets the probe so re-entering the same id resolves again.
    useEffect(() => {
        titleProbe.current = null;
    }, [selectionKey]);
    useEffect(() => {
        if (!item || item.kind === 'collection' || (item.title || '').trim()) return undefined;
        const sig = `${item.tmdb_id || ''}|${item.tvdb_id || ''}|${item.imdb_id || ''}`;
        if (sig === '||' || titleProbe.current === sig) return undefined;
        titleProbe.current = sig;
        let cancelled = false;
        (async () => {
            try {
                const resp = await cl2kMakerAPI.details(item.tmdb_id, item.kind, {
                    tvdbId: item.tvdb_id,
                    imdbId: item.imdb_id,
                });
                const title = resp?.data?.title;
                if (!cancelled && title) {
                    setItem(prev =>
                        prev && !(prev.title || '').trim()
                            ? { ...prev, title, year: prev.year ?? resp.data.year ?? null }
                            : prev
                    );
                }
            } catch {
                /* leave blank — the backend still backfills the filename on save */
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [item]);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const [cfgResp, statusResp] = await Promise.allSettled([
                    configAPI.fetchConfig({ useCache: false }),
                    cl2kMakerAPI.uploadStatus(),
                ]);
                if (cancelled) return;
                setConfig(
                    cfgResp.status === 'fulfilled' ? cfgResp.value?.data?.cl2k_maker || {} : {}
                );
                if (statusResp.status === 'fulfilled') {
                    setUploadStatus(statusResp.value?.data || null);
                }
            } catch {
                if (!cancelled) setConfig({});
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);

    return (
        <div className="p-4 md:p-6 max-w-6xl mx-auto pb-24">
            <PageHeader
                title="CL2K Poster Maker"
                description="Turn a TMDB/TVDB/IMDB title into a DAPS-named CL2K poster — pick the art and logo, optionally brush out text, then generate."
                icon="wallpaper"
            />

            <ConfigBanner config={config} uploadStatus={uploadStatus} />

            {!item ? (
                <TitlePicker onPick={pickItem} toast={toast} />
            ) : (
                <Builder
                    key={selectionKey}
                    item={item}
                    config={config}
                    uploadStatus={uploadStatus}
                    onReset={resetItem}
                    onItemChange={patch => setItem(prev => (prev ? { ...prev, ...patch } : prev))}
                    toast={toast}
                />
            )}
        </div>
    );
};

// ─── Config banner ───────────────────────────────────────────────────────

const ConfigBanner = ({ config, uploadStatus }) => {
    if (config === null) return null;
    const missingDir = !config.output_dir;
    // Upload is enabled but there's no usable Sync GDrive OAuth token, so every
    // upload will fail (a service account can't own files in a personal Drive).
    const uploadNoToken = uploadStatus?.upload_to_gdrive && uploadStatus?.token_ok === false;
    return (
        <section className="mt-4 p-3 bg-surface border border-border rounded-lg text-sm">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-secondary">
                <span>
                    <span className="text-tertiary">Output dir: </span>
                    {config.output_dir ? (
                        <span className="font-mono text-primary">{config.output_dir}</span>
                    ) : (
                        <span className="text-error">not configured</span>
                    )}
                </span>
                <span>
                    <span className="text-tertiary">Logo width: </span>
                    <span className="text-primary">{config.logo_max_width ?? 600}px</span>
                </span>
                <span>
                    <span className="text-tertiary">Whiten logo: </span>
                    <span className="text-primary">{config.whiten_logo ? 'yes' : 'no'}</span>
                </span>
                <span>
                    <span className="text-tertiary">AI provider: </span>
                    <span className="text-primary">{config.ai_provider || 'none'}</span>
                </span>
                <Link
                    to="/settings/modules"
                    className="text-primary underline hover:no-underline ml-auto"
                >
                    Edit in Module Settings →
                </Link>
            </div>
            {missingDir && (
                <div className="mt-2 text-xs text-error">
                    Set an output directory before generating, or saves will fail.
                </div>
            )}
            {uploadNoToken && (
                <div className="mt-2 text-xs text-warning">
                    Google Drive upload is enabled, but no usable Sync GDrive OAuth token is set —
                    uploads will fail. Add a token under{' '}
                    <Link
                        to="/settings/modules"
                        className="text-primary underline hover:no-underline"
                    >
                        Sync GDrive
                    </Link>{' '}
                    (a service account can’t own files in a personal Drive). Generation still
                    succeeds locally.
                </div>
            )}
        </section>
    );
};

// ─── Save destinations (shared across every save flow) ──────────────────────

// Hook owning the two independent save-target toggles. Drive defaults ON only
// when the module has Drive upload enabled AND a usable folder + token; output
// directory defaults ON. The default is applied once `uploadStatus` arrives so
// it never clobbers a user toggle.
const useSaveTargets = uploadStatus => {
    const [saveLocal, setSaveLocal] = useState(true);
    const [uploadGdrive, setUploadGdrive] = useState(false);
    const initRef = useRef(false);
    useEffect(() => {
        if (!uploadStatus || initRef.current) return;
        initRef.current = true;
        setUploadGdrive(
            !!uploadStatus.upload_to_gdrive &&
                !!uploadStatus.folder_id_set &&
                uploadStatus.token_ok !== false
        );
    }, [uploadStatus]);
    const noTarget = !saveLocal && !uploadGdrive;
    return {
        saveLocal,
        setSaveLocal,
        uploadGdrive,
        setUploadGdrive,
        uploadStatus,
        noTarget,
        // Request fields the backend reads (independent of how the UI is wired).
        fields: { save_local: saveLocal, upload_gdrive: uploadGdrive },
    };
};

// The two tick boxes. Drive is disabled (with a hint) when no folder is
// configured; an enabled-but-tokenless Drive choice warns it will fail.
const SaveTargets = ({ targets }) => {
    const { saveLocal, setSaveLocal, uploadGdrive, setUploadGdrive, uploadStatus, noTarget } =
        targets;
    const folderSet = !!uploadStatus?.folder_id_set;
    const tokenOk = uploadStatus?.token_ok !== false;
    return (
        <div className="border-t border-border-subtle pt-2 mt-1 flex flex-col gap-1">
            <span className="text-xs font-medium text-secondary">Save to</span>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
                <label className="flex items-center gap-2 text-sm text-primary">
                    <input
                        type="checkbox"
                        checked={saveLocal}
                        onChange={e => setSaveLocal(e.target.checked)}
                    />
                    Output directory
                </label>
                <label
                    className={`flex items-center gap-2 text-sm text-primary ${
                        folderSet ? '' : 'opacity-60'
                    }`}
                >
                    <input
                        type="checkbox"
                        checked={uploadGdrive}
                        disabled={!folderSet}
                        onChange={e => setUploadGdrive(e.target.checked)}
                    />
                    Google Drive
                </label>
            </div>
            {!folderSet && (
                <p className="text-xs text-tertiary">
                    Set a Drive folder under{' '}
                    <Link to="/settings/modules" className="text-primary underline">
                        Module Settings
                    </Link>{' '}
                    to enable Drive upload.
                </p>
            )}
            {uploadGdrive && folderSet && !tokenOk && (
                <p className="text-xs text-warning">
                    No usable Sync GDrive OAuth token — the Drive upload will fail (the poster still
                    saves locally if that box is ticked).
                </p>
            )}
            {noTarget && <p className="text-xs text-error">Select at least one destination.</p>}
        </div>
    );
};

// ─── Stage 1: title picker ─────────────────────────────────────────────────

const TitlePicker = ({ onPick, toast }) => {
    const [kind, setKind] = useState('movie');
    const [query, setQuery] = useState('');
    const [results, setResults] = useState([]);
    const [searching, setSearching] = useState(false);
    const [paste, setPaste] = useState('');
    const [resolving, setResolving] = useState(false);
    const [picking, setPicking] = useState(false);

    const runSearch = useCallback(
        async e => {
            e?.preventDefault();
            if (!query.trim()) return;
            setSearching(true);
            try {
                const resp = await cl2kMakerAPI.search(query.trim(), kind);
                setResults(resp?.data?.results || []);
            } catch (err) {
                toast.error(err.message || 'Search failed');
            } finally {
                setSearching(false);
            }
        },
        [query, kind, toast]
    );

    const pickResult = useCallback(
        async r => {
            const title = r.title || r.name || '';
            const dateStr = r.release_date || r.first_air_date || '';
            const base = {
                tmdb_id: r.id,
                kind,
                title,
                year: dateStr ? Number(dateStr.slice(0, 4)) : null,
                tvdb_id: null,
                imdb_id: null,
            };
            setPicking(true);
            try {
                // Auto-populate tvdb_id/imdb_id from TMDB so filenames match the
                // library; the manual "Edit IDs" editor stays as the fallback.
                onPick(await withExternalIds(base));
            } finally {
                setPicking(false);
            }
        },
        [kind, onPick]
    );

    const runPaste = useCallback(async () => {
        const parsed = parsePastedId(paste);
        if (!parsed) {
            toast.error('Could not parse an ID or URL');
            return;
        }
        setResolving(true);
        try {
            const pasteKind = parsed.type || kind;
            let tmdbId = parsed.source === 'tmdb' ? Number(parsed.id) : null;
            if (!tmdbId) {
                const resp = await cl2kMakerAPI.resolve(parsed.id, parsed.source, pasteKind);
                tmdbId = resp?.data?.tmdb_id;
            }
            if (!tmdbId) {
                toast.error('Could not resolve that ID to a TMDB id');
                return;
            }
            const base = {
                tmdb_id: Number(tmdbId),
                kind: pasteKind,
                title: '',
                year: null,
                tvdb_id: parsed.source === 'tvdb_id' ? Number(parsed.id) : null,
                imdb_id: parsed.source === 'imdb_id' ? parsed.id : null,
            };
            // Fill in whichever of tvdb/imdb the paste didn't already supply; the
            // blank title is resolved by the title-backfill effect once the item is
            // set (covers paste, Edit IDs and deep links uniformly).
            onPick(await withExternalIds(base));
        } catch (err) {
            toast.error(err.message || 'Resolve failed');
        } finally {
            setResolving(false);
        }
    }, [paste, kind, onPick, toast]);

    return (
        <section className="mt-6 p-4 bg-surface border border-border rounded-lg">
            <h2 className="text-lg font-semibold text-primary mb-3">Pick a title</h2>

            <div className="flex items-center gap-2 mb-3">
                <span className="text-sm text-secondary">Type</span>
                <select
                    value={kind}
                    onChange={e => setKind(e.target.value)}
                    className="bg-surface border border-border rounded px-2 py-1 text-sm text-primary"
                >
                    {KIND_OPTIONS.map(o => (
                        <option key={o.value} value={o.value}>
                            {o.label}
                        </option>
                    ))}
                </select>
            </div>

            <form onSubmit={runSearch} className="flex gap-2 mb-2">
                <input
                    type="text"
                    value={query}
                    onChange={e => setQuery(e.target.value)}
                    placeholder="Search TMDB by title…"
                    className="flex-1 bg-surface border border-border rounded px-3 py-2 text-sm text-primary"
                />
                <LoadingButton type="submit" loading={searching} icon="search">
                    Search
                </LoadingButton>
            </form>

            {results.length > 0 && (
                <ul className="divide-y divide-border border border-border rounded-md mb-4 max-h-80 overflow-auto">
                    {results.map(r => {
                        const title = r.title || r.name || '(untitled)';
                        const date = r.release_date || r.first_air_date || '';
                        return (
                            <li key={r.id}>
                                <button
                                    type="button"
                                    onClick={() => pickResult(r)}
                                    disabled={picking}
                                    className={`w-full text-left px-3 py-2 hover:bg-surface-alt flex items-center justify-between gap-3 ${
                                        picking ? 'opacity-60 cursor-wait' : ''
                                    }`}
                                >
                                    <span className="text-primary truncate">{title}</span>
                                    <span className="text-xs text-tertiary shrink-0">
                                        {date ? date.slice(0, 4) : '—'} · #{r.id}
                                    </span>
                                </button>
                            </li>
                        );
                    })}
                </ul>
            )}

            <div className="border-t border-border-subtle pt-3">
                <div className="text-sm text-secondary mb-2">
                    …or paste a TMDB / TVDB / IMDB ID or URL
                </div>
                <div className="flex gap-2">
                    <input
                        type="text"
                        value={paste}
                        onChange={e => setPaste(e.target.value)}
                        placeholder="e.g. 603, tt0133093, or a themoviedb.org URL"
                        className="flex-1 bg-surface border border-border rounded px-3 py-2 text-sm text-primary"
                    />
                    <LoadingButton
                        onClick={runPaste}
                        loading={resolving}
                        variant="secondary"
                        icon="link"
                    >
                        Use ID
                    </LoadingButton>
                </div>
            </div>
        </section>
    );
};

// ─── Stage 2–4: builder ────────────────────────────────────────────────────

// ─── ID editor (attach/clear tmdb/tvdb/imdb so filenames match the library) ──

const IdEditor = ({ item, onItemChange }) => {
    const numOrNull = v => (String(v).trim() === '' ? null : Number(v));
    const strOrNull = v => (String(v).trim() === '' ? null : String(v).trim());
    const inputCls =
        'flex-1 bg-surface border border-border rounded px-2 py-1 text-sm text-primary';
    const row = (lbl, el) => (
        <label className="flex items-center gap-2 text-sm text-secondary">
            <span className="w-16 shrink-0">{lbl}</span>
            {el}
        </label>
    );
    return (
        <div className="mt-3 pt-3 border-t border-border-subtle flex flex-col gap-2">
            <p className="text-xs text-tertiary">
                Set the ids that match your library — only the ids you fill get written to the
                filename. For a TVDB-only title (no TMDB entry), clear TMDB and add TVDB/IMDB.
            </p>
            {row(
                'Title',
                <input
                    type="text"
                    value={item.title || ''}
                    onChange={e => onItemChange({ title: e.target.value })}
                    className={inputCls}
                />
            )}
            {row(
                'Year',
                <input
                    type="number"
                    value={item.year ?? ''}
                    onChange={e => onItemChange({ year: numOrNull(e.target.value) })}
                    className={inputCls}
                />
            )}
            {row(
                'TMDB',
                <input
                    type="number"
                    value={item.tmdb_id ?? ''}
                    placeholder="(none)"
                    onChange={e => onItemChange({ tmdb_id: numOrNull(e.target.value) })}
                    className={inputCls}
                />
            )}
            {row(
                'TVDB',
                <input
                    type="number"
                    value={item.tvdb_id ?? ''}
                    placeholder="(none)"
                    onChange={e => onItemChange({ tvdb_id: numOrNull(e.target.value) })}
                    className={inputCls}
                />
            )}
            {row(
                'IMDB',
                <input
                    type="text"
                    value={item.imdb_id || ''}
                    placeholder="tt…"
                    onChange={e => onItemChange({ imdb_id: strOrNull(e.target.value) })}
                    className={inputCls}
                />
            )}
        </div>
    );
};

const Builder = ({ item, config, uploadStatus, onReset, onItemChange, toast }) => {
    // Restore the builder's selections from the session snapshot (written by the
    // effect below, cleared when a new title is picked) so they survive
    // navigation. Read once on mount.
    const saved = useMemo(() => ssRead(SS_BUILDER, {}), []);

    // 'upload-backdrop' was merged into the Edit-poster tab; migrate a saved tab.
    const [tab, setTab] = useState(
        saved.tab === 'upload-backdrop' ? 'edit' : (saved.tab ?? 'tmdb')
    );
    const [editIds, setEditIds] = useState(false);

    // Save destinations (output dir / Drive) — shared by every save flow below.
    const saveTargets = useSaveTargets(uploadStatus);

    // Art (shared across the TMDB / fanart tabs)
    const [tmdbArt, setTmdbArt] = useState(null);
    const [fanartArt, setFanartArt] = useState(null);
    // TMDB season-level posters (portrait 2:3) — only for season posters.
    const [seasonArt, setSeasonArt] = useState(null);
    const [loadingArt, setLoadingArt] = useState(true);
    const [backdrop, setBackdrop] = useState(saved.backdrop ?? null); // file_path | absolute url
    const [logo, setLogo] = useState(saved.logo ?? null);
    // Custom uploaded logo (one-off, not persisted): { b64, name, url }. When set
    // it overrides the chosen TMDB/fanart `logo` path.
    const [customLogo, setCustomLogo] = useState(null);
    const setCustomLogoExclusive = useCallback(c => {
        setCustomLogo(c);
        if (c) setLogo(null); // custom logo replaces a chosen TMDB/fanart logo
    }, []);

    // Crop framing. "cover" scales up + crops to fill (focal point below); "fit"
    // scales the backdrop down to the canvas width and black-pads the bottom so
    // subjects spread across a wide backdrop all stay in frame (the artist
    // technique). `crop` (0..1 {x,y,w,h}) isolates the subject region for fit mode.
    const [fitMode, setFitMode] = useState(saved.fitMode ?? 'cover');
    const [crop, setCrop] = useState(saved.crop ?? null);
    // Vertical position (0..1). In fit/extend it positions the fitted photo; in
    // Fill it pans the framing up at the same size (real artwork into the gradient).
    const [vPos, setVPos] = useState(saved.vPos ?? 0);
    // Zoom (>=1) for fit/extend: enlarge the subject above the full-width fit so a
    // wide backdrop isn't shrunk to a tiny strip.
    const [zoom, setZoom] = useState(saved.zoom ?? 1);
    const [focusX, setFocusX] = useState(saved.focusX ?? 0.5);
    const [focusY, setFocusY] = useState(saved.focusY ?? 0.5);

    // Logo size override (1 = the strict CL2K guide box; >1 enlarges the whole
    // guide-fit box past the width guides, capped only by the canvas).
    const [logoScale, setLogoScale] = useState(saved.logoScale ?? 1);
    // Logo vertical offset (px from the locked baseline; positive = down).
    const [logoYOffset, setLogoYOffset] = useState(saved.logoYOffset ?? 0);
    // Per-render whiten override; null = the module config (whiten_logo).
    const [whitenLogo, setWhitenLogo] = useState(saved.whitenLogo ?? null);
    const effectiveWhiten = whitenLogo === null ? (config?.whiten_logo ?? true) : whitenLogo;

    // Season variant (shows only)
    const [seasonNumber, setSeasonNumber] = useState(saved.seasonNumber ?? '');
    const [bulkSeasons, setBulkSeasons] = useState(saved.bulkSeasons ?? '');
    // Optional bottom banner (e.g. COMPLETE LIMITED SERIES). Overrides the auto
    // COLLECTION / season label; not applied to season posters (they show SEASON N).
    const [bandLabel, setBandLabel] = useState(saved.bandLabel ?? '');

    // AI text-removal
    const [removeText, setRemoveText] = useState(saved.removeText ?? false);
    const [maskB64, setMaskB64] = useState(null);
    const [brushSize, setBrushSize] = useState(18);

    // Persist the builder selections (not the ephemeral mask/preview) so the
    // in-progress poster is restored on return.
    useEffect(() => {
        ssWrite(SS_BUILDER, {
            tab,
            backdrop,
            logo,
            fitMode,
            crop,
            vPos,
            zoom,
            focusX,
            focusY,
            logoScale,
            logoYOffset,
            whitenLogo,
            seasonNumber,
            bulkSeasons,
            bandLabel,
            removeText,
        });
    }, [
        tab,
        backdrop,
        logo,
        fitMode,
        crop,
        vPos,
        zoom,
        focusX,
        focusY,
        logoScale,
        logoYOffset,
        whitenLogo,
        seasonNumber,
        bulkSeasons,
        bandLabel,
        removeText,
    ]);

    // Preview
    const [previewUrl, setPreviewUrl] = useState(null);
    const [previewing, setPreviewing] = useState(false);
    const [busy, setBusy] = useState(false);

    // A real (chosen/custom) logo is drawn as a live overlay on the logo-less base
    // so the size/position sliders move it without a server render. No logo = a
    // text wordmark, which is baked into the base instead (can't overlay it).
    //
    // Two processed variants: `processedBase` (no touch-up) is the STABLE image
    // the B/W touch-up brush draws over — it must not change as strokes land, or
    // the accumulated mask would be lost; `processedLogo` (touch-up applied) is
    // what the live overlay shows and the render bakes in.
    const hasLogo = !!(logo || customLogo);
    // Strokes are keyed to the (logo, whiten) they were drawn over: a stale key
    // makes the mask a derived no-op instead of needing a reset-in-effect.
    const flipKey = `${customLogo?.b64?.slice(0, 32) || logo}|${effectiveWhiten}`;
    const [logoFlip, setLogoFlip] = useState(null); // { key, b64 }
    const logoFlipB64 = logoFlip && logoFlip.key === flipKey ? logoFlip.b64 : null;
    const setLogoFlipB64 = useCallback(
        b64 => setLogoFlip(b64 ? { key: flipKey, b64 } : null),
        [flipKey]
    );
    const [processedBase, setProcessedBase] = useState(null);
    const [processedFlipped, setProcessedFlipped] = useState(null); // { forB64, data }
    const logoReq = useCallback(
        extra =>
            cl2kMakerAPI
                .logoProcessed({
                    ...(customLogo?.b64 ? { logo_b64: customLogo.b64 } : { logo_path: logo }),
                    whiten: effectiveWhiten,
                    ...extra,
                })
                .then(resp => {
                    const d = resp?.data;
                    return d?.b64
                        ? {
                              dataUrl: `data:image/png;base64,${d.b64}`,
                              width: d.width,
                              height: d.height,
                              maxWidth: d.max_width,
                          }
                        : null;
                }),
        [customLogo, logo, effectiveWhiten]
    );
    useEffect(() => {
        if (!hasLogo) return undefined; // no fetch; `overlayLogo` below hides it
        let cancelled = false;
        logoReq({})
            .then(d => {
                if (!cancelled) setProcessedBase(d);
            })
            .catch(() => {
                if (!cancelled) setProcessedBase(null);
            });
        return () => {
            cancelled = true;
        };
    }, [hasLogo, logoReq]);
    useEffect(() => {
        if (!logoFlipB64) return undefined; // overlay derives to the base below
        let cancelled = false;
        logoReq({ flip_b64: logoFlipB64 })
            .then(d => {
                if (!cancelled) setProcessedFlipped({ forB64: logoFlipB64, data: d });
            })
            .catch(() => {
                if (!cancelled) setProcessedFlipped(null);
            });
        return () => {
            cancelled = true;
        };
    }, [logoFlipB64, logoReq]);
    // Only show the overlay while a logo is selected (the fetched bytes may lag a
    // deselect by a tick). Derived, so no reset-setState in the effects above; the
    // flipped variant is used only while it matches the current mask.
    const processedLogo =
        logoFlipB64 && processedFlipped?.forB64 === logoFlipB64
            ? processedFlipped.data
            : processedBase;
    const overlayLogo = hasLogo ? processedLogo : null;

    const isSeasonPoster = item.kind === 'show' && String(seasonNumber).trim() !== '';
    const effectiveKind = isSeasonPoster ? 'season' : item.kind;

    // Load TMDB + fanart art. Builder is keyed by item, so selection/art state
    // starts fresh on each item — no synchronous resets needed here.
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const [tm, fa] = await Promise.allSettled([
                    cl2kMakerAPI.images(item.tmdb_id, item.kind),
                    cl2kMakerAPI.fanartImages({
                        tmdbId: item.tmdb_id,
                        type: item.kind,
                        tvdbId: item.tvdb_id,
                        imdbId: item.imdb_id,
                    }),
                ]);
                if (cancelled) return;
                if (tm.status === 'fulfilled') setTmdbArt(tm.value?.data || null);
                if (fa.status === 'fulfilled') setFanartArt(fa.value?.data || null);
            } finally {
                if (!cancelled) setLoadingArt(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [item]);

    // Season posters: TMDB has portrait 2:3 season-level key-art, a better source
    // than fitting a show backdrop. Fetch it when building a season poster.
    useEffect(() => {
        if (!isSeasonPoster || !item.tmdb_id) return undefined;
        let cancelled = false;
        (async () => {
            try {
                const resp = await cl2kMakerAPI.seasonImages(item.tmdb_id, Number(seasonNumber));
                if (!cancelled) setSeasonArt(resp?.data || null);
            } catch {
                if (!cancelled) setSeasonArt(null);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [item.tmdb_id, isSeasonPoster, seasonNumber]);

    // Revoke the preview object URL when it changes / unmounts.
    useEffect(() => {
        return () => {
            if (previewUrl) URL.revokeObjectURL(previewUrl);
        };
    }, [previewUrl]);

    const baseRequest = useMemo(
        () => ({
            kind: effectiveKind,
            title: item.title,
            tmdb_id: item.tmdb_id,
            year: item.year,
            tvdb_id: item.tvdb_id,
            imdb_id: item.imdb_id,
            season_number: isSeasonPoster ? Number(seasonNumber) : null,
            backdrop_path: backdrop,
            logo_path: logo,
            logo_b64: customLogo?.b64 || null,
            logo_scale: logoScale,
            logo_y_offset: logoYOffset,
            whiten: whitenLogo,
            logo_flip_b64: logoFlipB64,
            remove_text: removeText,
            mask_b64: removeText ? maskB64 : null,
            fit_mode: fitMode,
            focus_x: focusX,
            focus_y: focusY,
            crop_x: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.x : null,
            crop_y: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.y : null,
            crop_w: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.w : null,
            crop_h: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.h : null,
            // v_pos applies to every mode now (Fill pans up; fit/extend position).
            v_pos: vPos,
            zoom: fitMode === 'fit' || fitMode === 'extend' ? zoom : 1,
            // Banner overrides the auto label, but a season poster keeps its SEASON N.
            band_label: isSeasonPoster ? '' : bandLabel,
            // Save destinations (ignored by /preview, honoured by /generate).
            save_local: saveTargets.saveLocal,
            upload_gdrive: saveTargets.uploadGdrive,
        }),
        [
            effectiveKind,
            item,
            isSeasonPoster,
            seasonNumber,
            backdrop,
            logo,
            customLogo,
            logoScale,
            logoYOffset,
            whitenLogo,
            logoFlipB64,
            removeText,
            maskB64,
            fitMode,
            crop,
            vPos,
            zoom,
            focusX,
            focusY,
            bandLabel,
            saveTargets.saveLocal,
            saveTargets.uploadGdrive,
        ]
    );

    const setPreview = useCallback(blob => {
        const url = URL.createObjectURL(blob);
        setPreviewUrl(prev => {
            if (prev) URL.revokeObjectURL(prev);
            return url;
        });
    }, []);

    // Read the latest request inside the debounced effect without making its
    // identity a trigger (the effect fires off baseSig, below). The 550ms debounce
    // means the ref is always current by the time the timeout reads it.
    const baseRequestRef = useRef(baseRequest);
    useEffect(() => {
        baseRequestRef.current = baseRequest;
    }, [baseRequest]);

    // Signature of the fields that change the logo-less base. Logo size/position
    // (and title) are excluded when a real logo is chosen — the overlay handles
    // those live — and included only for the baked text-wordmark fallback.
    const baseSig = useMemo(
        () =>
            JSON.stringify({
                tab,
                k: effectiveKind,
                id: item.tmdb_id,
                sn: isSeasonPoster ? seasonNumber : null,
                bd: backdrop,
                fm: fitMode,
                c: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop : null,
                vp: vPos,
                zm: fitMode === 'fit' || fitMode === 'extend' ? zoom : 1,
                fx: focusX,
                fy: focusY,
                bl: isSeasonPoster ? '' : bandLabel,
                pl: !hasLogo,
                ti: hasLogo ? null : item.title,
                ls: hasLogo ? null : logoScale,
                ly: hasLogo ? null : logoYOffset,
            }),
        [
            tab,
            effectiveKind,
            item.tmdb_id,
            item.title,
            isSeasonPoster,
            seasonNumber,
            backdrop,
            fitMode,
            crop,
            vPos,
            zoom,
            focusX,
            focusY,
            bandLabel,
            hasLogo,
            logoScale,
            logoYOffset,
        ]
    );

    // Auto-render the cheap logo-less base shortly after a base-affecting change
    // settles — no more manual "Render preview" click for framing/backdrop/label.
    // AI text-removal is skipped here (slow); the Refresh button runs the full
    // render with AI when the user wants to see it.
    useEffect(() => {
        if (tab !== 'tmdb' && tab !== 'fanart') return undefined;
        if (!backdrop) return undefined; // RenderPanel hides a stale preview when backdrop is null
        let cancelled = false;
        const handle = setTimeout(async () => {
            setPreviewing(true);
            try {
                const blob = await cl2kMakerAPI.preview({
                    ...baseRequestRef.current,
                    place_logo: !hasLogo,
                    remove_text: false,
                    mask_b64: null,
                });
                if (!cancelled) setPreview(blob);
            } catch {
                /* auto-render stays quiet; the Refresh button surfaces errors */
            } finally {
                if (!cancelled) setPreviewing(false);
            }
        }, 550);
        return () => {
            cancelled = true;
            clearTimeout(handle);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [baseSig]);

    // Manual full refresh: re-render including AI text-removal (when enabled), and
    // bake the logo only for the text-wordmark fallback (a chosen logo stays a
    // live overlay so the sliders keep moving it).
    const runPreview = useCallback(async () => {
        setPreviewing(true);
        try {
            const blob = await cl2kMakerAPI.preview({ ...baseRequest, place_logo: !hasLogo });
            setPreview(blob);
        } catch (err) {
            toast.error(err.message || 'Preview failed');
        } finally {
            setPreviewing(false);
        }
    }, [baseRequest, hasLogo, setPreview, toast]);

    const runGenerate = useCallback(async () => {
        setBusy(true);
        try {
            // Building a poster here is a deliberate, one-off action, so always
            // overwrite — "already generated" (a stale provenance row, even after
            // the file was deleted) shouldn't block a manual Generate. The skip is
            // only meant for the unattended scheduled batch run.
            const resp = await cl2kMakerAPI.generate({ ...baseRequest, force: true });
            savedToast(toast, resp?.data, 'Generated');
        } catch (err) {
            toast.error(err.message || 'Generate failed');
        } finally {
            setBusy(false);
        }
    }, [baseRequest, toast]);

    const runPsdExport = useCallback(async () => {
        setBusy(true);
        try {
            const blob = await cl2kMakerAPI.psdExport(baseRequest);
            downloadBlob(blob, `${slugify(item.title) || item.tmdb_id}.psd`);
        } catch (err) {
            toast.error(err.message || 'PSD export failed');
        } finally {
            setBusy(false);
        }
    }, [baseRequest, item, toast]);

    const runBulkSeasons = useCallback(async () => {
        const nums = parseSeasonList(bulkSeasons);
        if (!nums.length) {
            toast.error('Enter season numbers, e.g. 1,2,3');
            return;
        }
        setBusy(true);
        try {
            const resp = await cl2kMakerAPI.generateSeasons({
                tmdb_id: item.tmdb_id,
                title: item.title,
                seasons: nums,
                year: item.year,
                tvdb_id: item.tvdb_id,
                imdb_id: item.imdb_id,
                fit_mode: fitMode,
                focus_x: focusX,
                focus_y: focusY,
                crop_x: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.x : null,
                crop_y: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.y : null,
                crop_w: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.w : null,
                crop_h: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.h : null,
                v_pos: vPos,
                zoom: fitMode === 'fit' || fitMode === 'extend' ? zoom : 1,
                logo_scale: logoScale,
                logo_y_offset: logoYOffset,
                // Deliberate manual action — overwrite existing season posters too.
                force: true,
            });
            const results = resp?.data?.results || [];
            const gen = results.filter(r => r.status === 'generated').length;
            toast.success(`Seasons: ${gen}/${results.length} generated`);
        } catch (err) {
            toast.error(err.message || 'Season generation failed');
        } finally {
            setBusy(false);
        }
    }, [
        bulkSeasons,
        item,
        fitMode,
        focusX,
        focusY,
        crop,
        vPos,
        zoom,
        logoScale,
        logoYOffset,
        toast,
    ]);

    const activeArt = tab === 'fanart' ? fanartArt : tmdbArt;
    const isRenderTab = tab === 'tmdb' || tab === 'fanart';

    // TMDB + fanart logos merged, for the uploaded-canvas tabs (which have no
    // source sub-tab of their own). De-duplicated by file_path.
    const allLogos = useMemo(() => {
        const merged = [...(tmdbArt?.logos || []), ...(fanartArt?.logos || [])];
        const seen = new Set();
        const deduped = merged.filter(l => {
            if (!l?.file_path || seen.has(l.file_path)) return false;
            seen.add(l.file_path);
            return true;
        });
        // Wordmark logos first. TMDB's "logos" array is polluted with portrait
        // character art (full-body renders of Goku/Vegeta/etc.) that whiten into
        // line-art garbage and render tiny in the landscape CL2K logo zone. Real
        // title wordmarks are wide (aspect ≳ 1.4); push tall/portrait images to the
        // end. Stable within each group; unknown dims (fanart clearlogos, already
        // proper wordmarks) rank with the wordmarks. Hides nothing — just orders.
        return deduped
            .map((l, i) => [l, i])
            .sort(([a, ai], [b, bi]) => {
                const score = x => (x.width && x.height && x.width / x.height < 1.4 ? 1 : 0);
                return score(a) - score(b) || ai - bi;
            })
            .map(([l]) => l);
    }, [tmdbArt, fanartArt]);

    // TMDB + fanart backdrops merged, for the square-art tab. De-duplicated.
    const allBackdrops = useMemo(() => {
        const merged = [...(tmdbArt?.backdrops || []), ...(fanartArt?.backdrops || [])];
        const seen = new Set();
        return merged.filter(b => {
            if (!b?.file_path || seen.has(b.file_path)) return false;
            seen.add(b.file_path);
            return true;
        });
    }, [tmdbArt, fanartArt]);

    return (
        <>
            {/* Selected title bar */}
            <section className="mt-6 p-4 bg-surface border border-border rounded-lg">
                <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                        <div className="text-lg font-semibold text-primary truncate">
                            {item.title || `TMDB #${item.tmdb_id}`}
                            {item.year ? (
                                <span className="text-tertiary font-normal"> ({item.year})</span>
                            ) : null}
                        </div>
                        <div className="text-xs text-tertiary mt-0.5">
                            {item.kind}
                            {item.tmdb_id ? ` · TMDB ${item.tmdb_id}` : ''}
                            {item.tvdb_id ? ` · TVDB ${item.tvdb_id}` : ''}
                            {item.imdb_id ? ` · ${item.imdb_id}` : ''}
                        </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                        <Button
                            onClick={() => setEditIds(v => !v)}
                            variant="secondary"
                            icon="tag"
                            size="small"
                        >
                            Edit IDs
                        </Button>
                        <Button onClick={onReset} variant="secondary" icon="arrow_back">
                            Change title
                        </Button>
                    </div>
                </div>
                {editIds && <IdEditor item={item} onItemChange={onItemChange} />}
            </section>

            {/* Stage 2: source tabs */}
            <div className="mt-6 flex flex-wrap gap-2">
                {SOURCE_TABS.map(t => (
                    <button
                        key={t.key}
                        type="button"
                        onClick={() => setTab(t.key)}
                        className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm border transition-colors ${
                            tab === t.key
                                ? 'bg-primary text-white border-primary'
                                : 'bg-surface text-secondary border-border hover:border-border-strong'
                        }`}
                    >
                        <span className="material-symbols-outlined text-base">{t.icon}</span>
                        {t.label}
                    </button>
                ))}
            </div>

            {/* Stage 3 + 4 panels */}
            {isRenderTab && (
                <RenderPanel
                    art={activeArt}
                    seasonArt={tab === 'tmdb' && isSeasonPoster ? seasonArt : null}
                    loadingArt={loadingArt}
                    source={tab}
                    backdrop={backdrop}
                    setBackdrop={setBackdrop}
                    logo={logo}
                    setLogo={setLogo}
                    customLogo={customLogo}
                    setCustomLogo={setCustomLogoExclusive}
                    logoScale={logoScale}
                    setLogoScale={setLogoScale}
                    logoYOffset={logoYOffset}
                    setLogoYOffset={setLogoYOffset}
                    whitenLogo={effectiveWhiten}
                    setWhitenLogo={setWhitenLogo}
                    logoTouchUpUrl={processedBase?.dataUrl || null}
                    onLogoFlip={setLogoFlipB64}
                    processedLogo={overlayLogo}
                    fitMode={fitMode}
                    setFitMode={setFitMode}
                    crop={crop}
                    setCrop={setCrop}
                    vPos={vPos}
                    setVPos={setVPos}
                    zoom={zoom}
                    setZoom={setZoom}
                    focusX={focusX}
                    focusY={focusY}
                    onFocusChange={(fx, fy) => {
                        setFocusX(fx);
                        setFocusY(fy);
                    }}
                    item={item}
                    config={config}
                    seasonNumber={seasonNumber}
                    setSeasonNumber={setSeasonNumber}
                    bandLabel={bandLabel}
                    setBandLabel={setBandLabel}
                    isSeasonPoster={isSeasonPoster}
                    bulkSeasons={bulkSeasons}
                    setBulkSeasons={setBulkSeasons}
                    onBulkSeasons={runBulkSeasons}
                    removeText={removeText}
                    setRemoveText={setRemoveText}
                    brushSize={brushSize}
                    setBrushSize={setBrushSize}
                    onMaskChange={setMaskB64}
                    previewUrl={previewUrl}
                    previewing={previewing}
                    onPreview={runPreview}
                    onGenerate={runGenerate}
                    onPsdExport={runPsdExport}
                    busy={busy}
                    saveTargets={saveTargets}
                />
            )}

            {tab === 'square' && (
                <SquareArtPanel
                    item={item}
                    backdrops={allBackdrops}
                    loadingArt={loadingArt}
                    saveTargets={saveTargets}
                    toast={toast}
                />
            )}
            {tab === 'background' && (
                <BackgroundArtPanel
                    item={item}
                    backdrops={allBackdrops}
                    loadingArt={loadingArt}
                    saveTargets={saveTargets}
                    toast={toast}
                />
            )}
            {tab === 'logo' && (
                <LogoAssetPanel
                    item={item}
                    logos={allLogos}
                    loadingArt={loadingArt}
                    saveTargets={saveTargets}
                    toast={toast}
                />
            )}

            {tab === 'upload-poster' && (
                <UploadPosterPanel
                    item={item}
                    effectiveKind={effectiveKind}
                    logos={allLogos}
                    loadingArt={loadingArt}
                    config={config}
                    saveTargets={saveTargets}
                    toast={toast}
                />
            )}
            {tab === 'edit' && (
                <EditPosterPanel
                    item={item}
                    effectiveKind={effectiveKind}
                    config={config}
                    logos={allLogos}
                    loadingArt={loadingArt}
                    saveTargets={saveTargets}
                    toast={toast}
                />
            )}

            <HistorySection toast={toast} />
        </>
    );
};

// ─── Render panel (TMDB / fanart) ──────────────────────────────────────────

const RenderPanel = ({
    art,
    seasonArt,
    loadingArt,
    source,
    backdrop,
    setBackdrop,
    logo,
    setLogo,
    customLogo,
    setCustomLogo,
    logoScale,
    setLogoScale,
    logoYOffset,
    setLogoYOffset,
    whitenLogo,
    setWhitenLogo,
    logoTouchUpUrl,
    onLogoFlip,
    processedLogo,
    fitMode,
    setFitMode,
    crop,
    setCrop,
    vPos,
    setVPos,
    zoom,
    setZoom,
    focusX,
    focusY,
    onFocusChange,
    item,
    config,
    seasonNumber,
    setSeasonNumber,
    bandLabel,
    setBandLabel,
    isSeasonPoster,
    bulkSeasons,
    setBulkSeasons,
    onBulkSeasons,
    removeText,
    setRemoveText,
    brushSize,
    setBrushSize,
    onMaskChange,
    previewUrl,
    previewing,
    onPreview,
    onGenerate,
    onPsdExport,
    busy,
    saveTargets,
}) => {
    const backdrops = art?.backdrops || [];
    const logos = art?.logos || [];
    const seasonPosters = seasonArt?.posters || [];
    const backdropUrl = backdrop ? urlForPath(backdrop) : null;
    // Template guide lines over the rendered preview (the PSD's cyan guides).
    const [showGuides, setShowGuides] = useState(true);

    return (
        <section className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Left: pickers + AI */}
            <div className="flex flex-col gap-4">
                {seasonPosters.length > 0 && (
                    <Picker
                        label="Season poster (tmdb)"
                        items={seasonPosters}
                        loading={false}
                        selected={backdrop}
                        onSelect={setBackdrop}
                        aspect="aspect-poster"
                        emptyText="No TMDB season posters."
                    />
                )}
                <Picker
                    label={`Backdrop (${source})`}
                    items={backdrops}
                    loading={loadingArt}
                    selected={backdrop}
                    onSelect={setBackdrop}
                    aspect="aspect-video"
                    emptyText="No backdrops from this source."
                />
                {/* Official posters: often the only quality art for small titles
                    (documentaries etc.) — pick one, brush the title text in the AI
                    panel below, erase, and build as usual. */}
                {(art?.posters || []).length > 0 && (
                    <Picker
                        label={`Poster (${source})`}
                        items={art.posters}
                        loading={loadingArt}
                        selected={backdrop}
                        onSelect={setBackdrop}
                        aspect="aspect-poster"
                        emptyText="No posters from this source."
                    />
                )}

                {backdropUrl && (
                    <CropFramer
                        imageUrl={backdropUrl}
                        fitMode={fitMode}
                        setFitMode={setFitMode}
                        crop={crop}
                        setCrop={setCrop}
                        vPos={vPos}
                        setVPos={setVPos}
                        zoom={zoom}
                        setZoom={setZoom}
                        focusX={focusX}
                        focusY={focusY}
                        onChange={onFocusChange}
                        mockLabel={
                            isSeasonPoster
                                ? `Season ${seasonNumber}`
                                : bandLabel || (item.kind === 'collection' ? 'COLLECTION' : '')
                        }
                        labelYFrac={
                            !isSeasonPoster && !bandLabel && item.kind === 'collection'
                                ? 1345 / 1500
                                : 1440 / 1500
                        }
                    />
                )}

                <LogoSelector
                    label={`Logo (${source})`}
                    logos={logos}
                    loading={loadingArt}
                    selected={logo}
                    onSelect={setLogo}
                    customLogo={customLogo}
                    onCustomChange={setCustomLogo}
                    scale={logoScale}
                    onScale={setLogoScale}
                    yOffset={logoYOffset}
                    onYOffset={setLogoYOffset}
                    whiten={whitenLogo}
                    onWhiten={setWhitenLogo}
                    touchUpUrl={logoTouchUpUrl}
                    onFlipMask={onLogoFlip}
                    emptyText="No logos from this source — upload a custom one, or a text wordmark is used as fallback."
                />

                {item.kind === 'show' && (
                    <SeasonControls
                        seasonNumber={seasonNumber}
                        setSeasonNumber={setSeasonNumber}
                        bulkSeasons={bulkSeasons}
                        setBulkSeasons={setBulkSeasons}
                        onBulkSeasons={onBulkSeasons}
                        busy={busy}
                    />
                )}

                {!isSeasonPoster && item.kind !== 'collection' && (
                    <div className="bg-surface border border-border rounded-lg p-3">
                        <label className="flex items-center gap-2 text-sm text-secondary">
                            <span className="w-28 text-primary font-medium">Banner</span>
                            <select
                                value={bandLabel}
                                onChange={e => setBandLabel(e.target.value)}
                                className="flex-1 bg-surface border border-border rounded px-2 py-1 text-sm text-primary"
                            >
                                {BAND_LABEL_OPTIONS.map(o => (
                                    <option key={o.value} value={o.value}>
                                        {o.label}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <p className="text-xs text-tertiary mt-2">
                            Optional bottom banner in the CL2K label band (e.g. a limited series).
                        </p>
                    </div>
                )}

                <AiPanel
                    config={config}
                    removeText={removeText}
                    setRemoveText={setRemoveText}
                    brushSize={brushSize}
                    setBrushSize={setBrushSize}
                    backdropUrl={backdropUrl}
                    onMaskChange={onMaskChange}
                />
            </div>

            {/* Right: preview + output — sticky so it stays in view while the long
                left control column scrolls (seeing the preview is the whole point). */}
            <div className="flex flex-col gap-3 self-start sticky top-4 max-h-screen overflow-y-auto">
                <div className="bg-surface border border-border rounded-lg p-3">
                    <div className="flex items-center justify-between mb-2">
                        <h3 className="text-sm font-medium text-primary">Preview</h3>
                        <div className="flex items-center gap-3">
                            <GuidesToggle show={showGuides} onChange={setShowGuides} />
                            <LoadingButton
                                onClick={onPreview}
                                loading={previewing}
                                disabled={!backdrop}
                                icon="refresh"
                                size="small"
                            >
                                Refresh
                            </LoadingButton>
                        </div>
                    </div>
                    <div className="relative aspect-[2/3] bg-black rounded overflow-hidden flex items-center justify-center">
                        {backdrop && previewUrl ? (
                            <>
                                <img
                                    src={previewUrl}
                                    alt="CL2K preview"
                                    className="w-full h-full object-contain"
                                />
                                {processedLogo && (
                                    <LogoOverlay
                                        logo={processedLogo}
                                        scale={logoScale}
                                        yOffset={logoYOffset}
                                    />
                                )}
                                {showGuides && <GuideOverlay />}
                            </>
                        ) : (
                            <span className="text-xs text-tertiary px-4 text-center">
                                {!backdrop
                                    ? 'Select a backdrop to start.'
                                    : previewing
                                      ? 'Rendering preview…'
                                      : 'Preview unavailable — tap Refresh.'}
                            </span>
                        )}
                    </div>
                </div>

                <div className="bg-surface border border-border rounded-lg p-3 flex flex-col gap-2">
                    <h3 className="text-sm font-medium text-primary">Output</h3>
                    <SaveTargets targets={saveTargets} />
                    <LoadingButton
                        onClick={onGenerate}
                        loading={busy}
                        disabled={!backdrop || saveTargets.noTarget}
                        icon="save"
                    >
                        Generate &amp; save
                    </LoadingButton>
                    <div className="flex gap-2">
                        <LoadingButton
                            onClick={onPsdExport}
                            loading={busy}
                            disabled={!backdrop}
                            variant="secondary"
                            icon="layers"
                        >
                            Export .psd
                        </LoadingButton>
                        {backdropUrl && (
                            <a
                                href={backdropUrl}
                                download
                                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm border border-border text-secondary hover:border-border-strong"
                                title="Download the backdrop to clean externally (Firefly/Photoshop), then re-import via the Edit poster tab"
                            >
                                <span className="material-symbols-outlined text-base">
                                    download
                                </span>
                                Backdrop
                            </a>
                        )}
                    </div>
                    <p className="text-xs text-tertiary">
                        Handoff: download the backdrop, clean it in Firefly/Photoshop, then bring it
                        back via the <span className="text-secondary">Edit poster</span> tab.
                    </p>
                </div>
            </div>
        </section>
    );
};

const SeasonControls = ({
    seasonNumber,
    setSeasonNumber,
    bulkSeasons,
    setBulkSeasons,
    onBulkSeasons,
    busy,
}) => (
    <div className="bg-surface border border-border rounded-lg p-3 flex flex-col gap-3">
        <h3 className="text-sm font-medium text-primary">Season variant</h3>
        <label className="flex items-center gap-2 text-sm text-secondary">
            <span className="w-28">Season number</span>
            <input
                type="number"
                min="0"
                value={seasonNumber}
                onChange={e => setSeasonNumber(e.target.value)}
                placeholder="blank = main show poster"
                className="flex-1 bg-surface border border-border rounded px-2 py-1 text-sm text-primary"
            />
        </label>
        <div className="flex items-center gap-2">
            <input
                type="text"
                value={bulkSeasons}
                onChange={e => setBulkSeasons(e.target.value)}
                placeholder="Generate all: 1,2,3"
                className="flex-1 bg-surface border border-border rounded px-2 py-1 text-sm text-primary"
            />
            <LoadingButton
                onClick={onBulkSeasons}
                loading={busy}
                variant="secondary"
                icon="grid_view"
                size="small"
            >
                Generate seasons
            </LoadingButton>
        </div>
        <p className="text-xs text-tertiary">
            Each season reuses the show&apos;s stored backdrop; only the season number changes.
        </p>
    </div>
);

// ─── AI text-removal panel + brush canvas ──────────────────────────────────

const AiPanel = ({
    config,
    removeText,
    setRemoveText,
    brushSize,
    setBrushSize,
    backdropUrl,
    onMaskChange,
}) => {
    const provider = config?.ai_provider || 'none';
    return (
        <div className="bg-surface border border-border rounded-lg p-3 flex flex-col gap-3">
            <label className="flex items-center gap-2 text-sm text-primary font-medium">
                <input
                    type="checkbox"
                    checked={removeText}
                    onChange={e => setRemoveText(e.target.checked)}
                />
                Remove text with AI
            </label>
            <p className="text-xs text-tertiary">
                Provider: <span className="text-secondary">{provider}</span>. OpenAI re-imagines the
                whole image — brush a mask over just the text to keep faces/art intact. Set the
                provider/key in{' '}
                <Link to="/settings/modules" className="text-primary underline hover:no-underline">
                    Module Settings
                </Link>
                .
            </p>
            {removeText && provider === 'none' && (
                <div className="text-xs text-warning">
                    AI provider is “none” — enable one in settings or this has no effect.
                </div>
            )}
            {removeText && (
                <>
                    <label className="flex items-center gap-2 text-sm text-secondary">
                        <span className="w-20">Brush</span>
                        <input
                            type="range"
                            min="4"
                            max="60"
                            value={brushSize}
                            onChange={e => setBrushSize(Number(e.target.value))}
                            className="flex-1"
                        />
                        <span className="w-10 text-right">{brushSize}px</span>
                    </label>
                    {backdropUrl ? (
                        <BrushMask
                            imageUrl={backdropUrl}
                            brushSize={brushSize}
                            onMaskChange={onMaskChange}
                        />
                    ) : (
                        <div className="text-xs text-tertiary">
                            Select a backdrop to brush a mask over.
                        </div>
                    )}
                </>
            )}
        </div>
    );
};

/**
 * Brush a white-on-black mask over the backdrop. White = remove. The canvas
 * backing store holds opaque white strokes on a transparent background; CSS
 * opacity only dims the display, so toDataURL still yields a clean mask that the
 * backend resizes to the backdrop and feeds to the AI inpainter.
 */
const BrushMask = ({ imageUrl, brushSize, onMaskChange }) => {
    const canvasRef = useRef(null);
    const drawing = useRef(false);

    const sizeToImage = useCallback(img => {
        const c = canvasRef.current;
        if (!c) return;
        c.width = img.clientWidth;
        c.height = img.clientHeight;
    }, []);

    const pointFor = useCallback(e => {
        const c = canvasRef.current;
        const rect = c.getBoundingClientRect();
        const clientX = e.touches?.[0]?.clientX ?? e.clientX;
        const clientY = e.touches?.[0]?.clientY ?? e.clientY;
        return {
            x: (clientX - rect.left) * (c.width / rect.width),
            y: (clientY - rect.top) * (c.height / rect.height),
        };
    }, []);

    const paint = useCallback(
        p => {
            const ctx = canvasRef.current.getContext('2d');
            ctx.fillStyle = '#ffffff';
            ctx.beginPath();
            ctx.arc(p.x, p.y, brushSize, 0, Math.PI * 2);
            ctx.fill();
        },
        [brushSize]
    );

    const emit = useCallback(() => {
        const data = canvasRef.current.toDataURL('image/png').split(',')[1];
        onMaskChange(data);
    }, [onMaskChange]);

    const onDown = useCallback(
        e => {
            e.preventDefault();
            drawing.current = true;
            paint(pointFor(e));
        },
        [paint, pointFor]
    );
    const onMove = useCallback(
        e => {
            if (!drawing.current) return;
            paint(pointFor(e));
        },
        [paint, pointFor]
    );
    const onUp = useCallback(() => {
        if (!drawing.current) return;
        drawing.current = false;
        emit();
    }, [emit]);

    const clear = useCallback(() => {
        const c = canvasRef.current;
        c.getContext('2d').clearRect(0, 0, c.width, c.height);
        onMaskChange(null);
    }, [onMaskChange]);

    return (
        <div className="flex flex-col gap-2">
            <div className="relative inline-block leading-none select-none">
                <img
                    src={imageUrl}
                    alt="Backdrop to mask"
                    onLoad={e => sizeToImage(e.target)}
                    className="block max-w-full rounded"
                    draggable={false}
                />
                <canvas
                    ref={canvasRef}
                    className="absolute inset-0 cursor-crosshair rounded"
                    style={{ opacity: 0.5, touchAction: 'none' }}
                    onMouseDown={onDown}
                    onMouseMove={onMove}
                    onMouseUp={onUp}
                    onMouseLeave={onUp}
                    onTouchStart={onDown}
                    onTouchMove={onMove}
                    onTouchEnd={onUp}
                />
            </div>
            <div>
                <Button onClick={clear} variant="secondary" icon="ink_eraser" size="small">
                    Clear mask
                </Button>
            </div>
        </div>
    );
};

// ─── Crop framing (draggable focal point) ───────────────────────────────────

const clamp01 = v => Math.max(0, Math.min(1, v));

/**
 * Drag a 2:3 crop box over the wide backdrop to choose what stays in frame.
 * The box mirrors exactly what the backend keeps: the largest 2:3 rectangle that
 * fits the backdrop, positioned by the focal point. Everything outside is dimmed.
 * Reports focus_x/focus_y (0..1, the box centre) so /preview + /generate crop the
 * same way. Drag anywhere on the image to move the focal point.
 */
// Two framing modes:
//  - "cover" (Fill): drag a focal point; a fixed 2:3 box scales up + crops to fill
//    the canvas. Best when the subject already fills a ~2:3 region.
//  - "fit" (Fit): drag a free-form rectangle around the subjects; that region is
//    scaled DOWN to the canvas width and black-padded at the bottom, so subjects
//    spread across a wide backdrop all stay in frame (the artist technique). The
//    black band is the CL2K gradient/logo zone.
const FULL_CROP = { x: 0, y: 0, w: 1, h: 1 };

const FRAMING_HELP = {
    cover: 'Drag on the photo to choose what stays in the 2:3 crop — the dimmed area is cut. Use Vertical position to slide the framing up at the same size; real artwork flows down into the gradient (no AI).',
    fit: 'Drag a box around the subjects: that region shrinks to the poster width (use Zoom to enlarge it), sky is extended above, and the bottom fades to black into the logo zone. The mock shows where it lands.',
    extend: 'Drag a box around the subjects (use Zoom to enlarge them): the empty bottom is filled by AI on Generate. The mock shows the free edge-extend placeholder until then.',
};

// Live miniature of the final 2:3 canvas for fit/extend framing. Updates instantly
// as the crop box / vertical-position slider move (no server render): shows the
// cropped region's placement, the stretched-sky fill above, the fade-to-black
// below, the template gradient, the logo zone and the label band. Mirrors the
// backend geometry (gradient 780→1375, logo bottom 1300, label 1440/1345 of 1500).
const FitMock = ({ imageUrl, ratio, crop, vPos, label, labelYFrac }) => {
    const c = crop || FULL_CROP;
    if (!ratio || c.w < 0.02 || c.h < 0.02) return null;
    const photoH = Math.min(1, (2 / 3) * ((c.h * ratio) / c.w)); // frac of canvas height
    const top = clamp01(vPos) * Math.max(0, 1 - photoH);
    const bottomFillH = Math.min(1 - top - photoH, 0.18);
    // Shared horizontal mapping: scale the full image so the crop's x-range fills
    // the mock width.
    const imgW = `${100 / c.w}%`;
    const imgLeft = `-${(c.x / c.w) * 100}%`;
    const skySliver = 0.03 * c.h; // thin top-of-crop sliver, stretched (as backend does)
    return (
        <div className="shrink-0">
            <div
                className="relative overflow-hidden rounded border border-border bg-black"
                style={{ width: 150, height: 225 }}
            >
                {top > 0.002 && (
                    <div
                        className="absolute left-0 w-full overflow-hidden"
                        style={{ top: 0, height: `${top * 100}%` }}
                    >
                        <img
                            src={imageUrl}
                            alt=""
                            className="absolute"
                            style={{
                                width: imgW,
                                left: imgLeft,
                                height: `${100 / Math.max(skySliver, 0.005)}%`,
                                top: `-${(c.y / Math.max(skySliver, 0.005)) * 100}%`,
                                filter: 'blur(6px)',
                            }}
                        />
                    </div>
                )}
                <div
                    className="absolute left-0 w-full overflow-hidden"
                    style={{ top: `${top * 100}%`, height: `${photoH * 100}%` }}
                >
                    <img
                        src={imageUrl}
                        alt=""
                        className="absolute max-w-none"
                        style={{
                            width: imgW,
                            left: imgLeft,
                            top: `-${(c.y / c.h) * 100}%`,
                        }}
                    />
                </div>
                {bottomFillH > 0.002 && (
                    <div
                        className="absolute left-0 w-full overflow-hidden"
                        style={{ top: `${(top + photoH) * 100}%`, height: `${bottomFillH * 100}%` }}
                    >
                        <img
                            src={imageUrl}
                            alt=""
                            className="absolute"
                            style={{
                                width: imgW,
                                left: imgLeft,
                                height: `${100 / Math.max(skySliver, 0.005)}%`,
                                top: `-${((c.y + c.h - skySliver) / Math.max(skySliver, 0.005)) * 100}%`,
                                filter: 'blur(6px)',
                            }}
                        />
                        <div
                            className="absolute inset-0"
                            style={{
                                background: 'linear-gradient(180deg, rgba(0,0,0,0.3), #000 90%)',
                            }}
                        />
                    </div>
                )}
                {/* Template gradient (780→1375 of 1500) */}
                <div
                    className="absolute inset-0 pointer-events-none"
                    style={{
                        background:
                            'linear-gradient(180deg, rgba(0,0,0,0) 52%, rgba(0,0,0,0.55) 76%, #000 91.7%)',
                    }}
                />
                {/* Logo zone (bottom-aligned at y=1300) */}
                <div
                    className="absolute pointer-events-none flex items-end justify-center"
                    style={{
                        left: '20%',
                        width: '60%',
                        top: '73.3%',
                        height: '13.4%',
                        border: '1px dashed rgba(255,255,255,0.35)',
                        borderRadius: 3,
                    }}
                >
                    <span style={{ fontSize: 8, color: 'rgba(255,255,255,0.5)', lineHeight: 1.6 }}>
                        LOGO
                    </span>
                </div>
                {label ? (
                    <div
                        className="absolute w-full text-center pointer-events-none"
                        style={{
                            top: `${labelYFrac * 100}%`,
                            transform: 'translateY(-50%)',
                            color: '#fff',
                            fontSize: 7,
                            letterSpacing: 2,
                            fontFamily: 'Arial, sans-serif',
                        }}
                    >
                        {label.toUpperCase()}
                    </div>
                ) : null}
            </div>
            <p className="text-xs text-tertiary mt-1 text-center" style={{ width: 150 }}>
                Live mock (approx.)
            </p>
        </div>
    );
};

const CropFramer = ({
    imageUrl,
    fitMode,
    setFitMode,
    crop,
    setCrop,
    vPos,
    setVPos,
    zoom,
    setZoom,
    focusX,
    focusY,
    onChange,
    mockLabel = '',
    labelYFrac = 1440 / 1500,
}) => {
    const wrapRef = useRef(null);
    // Natural aspect ratio (h/w) of the backdrop — display-size independent, so
    // the overlay/drag math stays correct when layout (e.g. the live mock beside
    // the image) resizes the displayed image without a reload.
    const [ratio, setRatio] = useState(null);
    const dragging = useRef(false);
    const anchor = useRef(null); // box-draw anchor (normalized)
    // Both "fit" and "extend" use the free-form keep-region box; only "cover" uses
    // the focal-point 2:3 box.
    const isBox = fitMode === 'fit' || fitMode === 'extend';

    // Cover-mode 2:3 box positioned by the focal point (fractions of the image).
    const coverRect = useMemo(() => {
        if (!ratio) return null;
        const target = 2 / 3; // CL2K canvas aspect (w:h)
        let wF, hF;
        if (1 / ratio > target) {
            hF = 1;
            wF = target * ratio;
        } else {
            wF = 1;
            hF = 1 / target / ratio;
        }
        const leftF = Math.max(0, Math.min(focusX - wF / 2, 1 - wF));
        const topF = Math.max(0, Math.min(focusY - hF / 2, 1 - hF));
        return { left: leftF, top: topF, w: wF, h: hF };
    }, [ratio, focusX, focusY]);

    // Box-mode kept-region from the normalized crop (already fractions).
    const boxRect = useMemo(() => {
        if (!isBox) return null;
        const c = crop || FULL_CROP;
        return { left: c.x, top: c.y, w: c.w, h: c.h };
    }, [isBox, crop]);

    const pointFromEvent = useCallback(e => {
        const el = wrapRef.current;
        if (!el) return null;
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) return null;
        const cx = (e.touches?.[0]?.clientX ?? e.clientX) - r.left;
        const cy = (e.touches?.[0]?.clientY ?? e.clientY) - r.top;
        return { nx: clamp01(cx / r.width), ny: clamp01(cy / r.height) };
    }, []);

    const down = useCallback(
        e => {
            e.preventDefault();
            const p = pointFromEvent(e);
            if (!p) return;
            dragging.current = true;
            if (isBox) {
                anchor.current = p;
                setCrop({ x: p.nx, y: p.ny, w: 0, h: 0 });
            } else {
                onChange(p.nx, p.ny);
            }
        },
        [isBox, pointFromEvent, onChange, setCrop]
    );
    const moveEvt = useCallback(
        e => {
            if (!dragging.current) return;
            const p = pointFromEvent(e);
            if (!p) return;
            if (isBox && anchor.current) {
                const a = anchor.current;
                setCrop({
                    x: Math.min(a.nx, p.nx),
                    y: Math.min(a.ny, p.ny),
                    w: Math.abs(p.nx - a.nx),
                    h: Math.abs(p.ny - a.ny),
                });
            } else if (!isBox) {
                onChange(p.nx, p.ny);
            }
        },
        [isBox, pointFromEvent, onChange, setCrop]
    );
    const up = useCallback(() => {
        // A tiny accidental box collapses back to the whole image.
        if (isBox && crop && (crop.w < 0.05 || crop.h < 0.05)) setCrop(FULL_CROP);
        dragging.current = false;
        anchor.current = null;
    }, [isBox, crop, setCrop]);

    const selectBox = useCallback(
        mode => {
            setFitMode(mode);
            if (!crop) setCrop(FULL_CROP);
        },
        [setFitMode, crop, setCrop]
    );

    const activeRect = isBox ? boxRect : coverRect;

    // The region the live mock should render, accounting for the new controls:
    //  - fit/extend: shrink the box horizontally by 1/zoom (centred) so the mock
    //    magnifies the subject like the backend's side-cropping zoom.
    //  - cover (Fill): shift the cover crop down within its own height by ~30%·vPos
    //    so the framing reads as panned UP, with the floor fading to black below.
    const mockCrop = useMemo(() => {
        if (isBox) {
            const c = crop || FULL_CROP;
            const z = Math.max(1, zoom || 1);
            if (z <= 1) return c;
            const w = c.w / z;
            return { x: c.x + (c.w - w) / 2, y: c.y, w, h: c.h };
        }
        if (!coverRect) return null;
        const shift = clamp01(vPos) * 0.3 * coverRect.h;
        return {
            x: coverRect.left,
            y: Math.min(coverRect.top + shift, coverRect.top + coverRect.h - 0.05),
            w: coverRect.w,
            h: Math.max(0.05, coverRect.h - shift),
        };
    }, [isBox, crop, zoom, coverRect, vPos]);

    return (
        <div className="bg-surface border border-border rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-medium text-primary">Crop framing</h3>
                <div className="flex items-center gap-1">
                    <Button
                        onClick={() => setFitMode('cover')}
                        variant={fitMode === 'cover' ? 'primary' : 'secondary'}
                        size="small"
                    >
                        Fill
                    </Button>
                    <Button
                        onClick={() => selectBox('fit')}
                        variant={fitMode === 'fit' ? 'primary' : 'secondary'}
                        size="small"
                    >
                        Fit
                    </Button>
                    <Button
                        onClick={() => selectBox('extend')}
                        variant={fitMode === 'extend' ? 'primary' : 'secondary'}
                        size="small"
                    >
                        Extend (AI)
                    </Button>
                    <Button
                        onClick={() => (isBox ? setCrop(FULL_CROP) : onChange(0.5, 0.5))}
                        variant="secondary"
                        icon={isBox ? 'crop_free' : 'filter_center_focus'}
                        size="small"
                    >
                        {isBox ? 'Whole image' : 'Center'}
                    </Button>
                </div>
            </div>
            <p className="text-xs text-tertiary mb-2">
                {FRAMING_HELP[fitMode] || FRAMING_HELP.cover}
            </p>
            <label className="flex items-center gap-2 text-xs text-secondary mb-2">
                <span className="shrink-0 w-24">Vertical position</span>
                <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.01"
                    value={vPos}
                    onChange={e => setVPos(Number(e.target.value))}
                    className="flex-1"
                />
                <span className="w-16 shrink-0 text-tertiary">
                    {vPos < 0.02
                        ? isBox
                            ? 'top'
                            : 'default'
                        : isBox
                          ? `${Math.round(vPos * 100)}% down`
                          : `${Math.round(vPos * 100)}% up`}
                </span>
            </label>
            {isBox && (
                <label className="flex items-center gap-2 text-xs text-secondary mb-2">
                    <span className="shrink-0 w-24">Zoom</span>
                    <input
                        type="range"
                        min="1"
                        max="3"
                        step="0.05"
                        value={zoom ?? 1}
                        onChange={e => setZoom(Number(e.target.value))}
                        className="flex-1"
                    />
                    <span className="w-16 shrink-0 text-tertiary">{(zoom ?? 1).toFixed(2)}×</span>
                </label>
            )}
            <div className="flex gap-3 items-start">
                <div
                    ref={wrapRef}
                    className="relative inline-block leading-none select-none overflow-hidden rounded cursor-crosshair min-w-0"
                    onMouseDown={down}
                    onMouseMove={moveEvt}
                    onMouseUp={up}
                    onMouseLeave={up}
                    onTouchStart={down}
                    onTouchMove={moveEvt}
                    onTouchEnd={up}
                >
                    <img
                        src={imageUrl}
                        alt="Crop framing"
                        onLoad={e =>
                            setRatio(
                                e.target.naturalWidth
                                    ? e.target.naturalHeight / e.target.naturalWidth
                                    : null
                            )
                        }
                        className="block max-w-full"
                        draggable={false}
                    />
                    {activeRect && (
                        <div
                            className="absolute border-2 border-primary"
                            style={{
                                left: `${activeRect.left * 100}%`,
                                top: `${activeRect.top * 100}%`,
                                width: `${activeRect.w * 100}%`,
                                height: `${activeRect.h * 100}%`,
                                boxShadow: '0 0 0 9999px rgba(0,0,0,0.5)',
                                pointerEvents: 'none',
                            }}
                        />
                    )}
                </div>
                <FitMock
                    imageUrl={imageUrl}
                    ratio={ratio}
                    crop={mockCrop}
                    vPos={isBox ? vPos : 0}
                    label={mockLabel}
                    labelYFrac={labelYFrac}
                />
            </div>
        </div>
    );
};

// ─── Picker grid ───────────────────────────────────────────────────────────

const Picker = ({ label, items, loading, selected, onSelect, aspect, onBlack, emptyText }) => (
    <div className="bg-surface border border-border rounded-lg p-3">
        <h3 className="text-sm font-medium text-primary mb-2">{label}</h3>
        {loading ? (
            <div className="text-xs text-tertiary py-4">Loading…</div>
        ) : items.length === 0 ? (
            <div className="text-xs text-tertiary py-2">{emptyText}</div>
        ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-72 overflow-auto">
                {items.map((it, idx) => {
                    const path = it.file_path;
                    const isSel = selected === path;
                    return (
                        <button
                            key={`${path}-${idx}`}
                            type="button"
                            onClick={() => onSelect(isSel ? null : path)}
                            aria-pressed={isSel}
                            className={`relative ${aspect} rounded-md overflow-hidden border-2 transition-all ${
                                isSel
                                    ? 'border-primary ring-2 ring-primary/40'
                                    : 'border-border hover:border-border-strong'
                            } ${onBlack ? 'bg-black' : 'bg-surface-alt'}`}
                            title={
                                it.width
                                    ? `${it.width}×${it.height}${
                                          'iso_639_1' in it
                                              ? ` (${it.iso_639_1 || 'textless'})`
                                              : ''
                                      }`
                                    : path
                            }
                        >
                            <img
                                src={it.url || urlForPath(path)}
                                alt=""
                                loading="lazy"
                                className="absolute inset-0 w-full h-full object-contain"
                            />
                            {isSel && (
                                <span className="absolute top-1 right-1 inline-flex items-center justify-center w-5 h-5 rounded-full bg-primary text-white">
                                    <span className="material-symbols-outlined text-sm">check</span>
                                </span>
                            )}
                            {it.width ? (
                                <span className="absolute bottom-0 right-0 text-[11px] font-mono text-white bg-black/60 px-1">
                                    {it.width}×{it.height}
                                </span>
                            ) : null}
                            {/* Language badge: 'textless' (null language) art is pure
                                artwork — no AI text pass needed at all. */}
                            {'iso_639_1' in it ? (
                                <span className="absolute bottom-0 left-0 text-[11px] font-mono text-white bg-black/60 px-1">
                                    {it.iso_639_1 || 'textless'}
                                </span>
                            ) : null}
                        </button>
                    );
                })}
            </div>
        )}
    </div>
);

// ─── CL2K guide overlay ──────────────────────────────────────────────────────

// The template's own guides (mined from CL2K_template.psd), drawn over a 2:3
// poster preview as Photoshop-style cyan lines. Positions are fractions of the
// 1000×1500 canvas, so the overlay lines up with any rendered preview. Each line
// explains itself on hover (what the guide means) — that's the point of the
// overlay, since the lines alone are cryptic. Inline styles only — this must not
// depend on utility classes existing.
const CL2K_GUIDES = [
    { label: 'Max logo width', o: 'x', p: 100 },
    { label: 'Main logo width (600px box)', o: 'x', p: 200 },
    { label: 'Main logo width (600px box)', o: 'x', p: 800 },
    { label: 'Max logo width', o: 'x', p: 900 },
    { label: 'Logo zone top — logos shouldn’t rise above this line', o: 'y', p: 1100 },
    { label: 'Logo bottom baseline', o: 'y', p: 1319 },
    { label: 'Label band (COLLECTION / SEASON)', o: 'y', p: 1352 },
    { label: 'Gradient darkest line', o: 'y', p: 1375 },
];
const GUIDE_CYAN = 'rgba(0, 255, 255, 0.6)';
const GUIDE_CYAN_HOVER = 'rgba(0, 255, 255, 0.95)';

// One guide line + its hover label. A wide transparent strip is the hover target
// (a 1px line is near-impossible to hover); the visible line sits centred inside
// it. The label chip is anchored to grow toward the canvas centre so it never
// clips at the preview edge.
const GuideLine = ({ label, o, p }) => {
    const [hover, setHover] = useState(false);
    const vertical = o === 'x';
    const at = vertical ? `${p / 10}%` : `${p / 15}%`;
    const strip = vertical
        ? { top: 0, bottom: 0, left: at, width: 12, marginLeft: -6 }
        : { left: 0, right: 0, top: at, height: 12, marginTop: -6 };
    const line = vertical
        ? { top: 0, bottom: 0, left: 6, width: 1 }
        : { left: 0, right: 0, top: 6, height: 1 };
    const chip = vertical
        ? { top: 6, ...(p < 500 ? { left: 8 } : { right: 8 }) }
        : { left: 8, top: 6, transform: 'translateY(-50%)' };
    return (
        <div
            style={{ position: 'absolute', pointerEvents: 'auto', cursor: 'help', ...strip }}
            onMouseEnter={() => setHover(true)}
            onMouseLeave={() => setHover(false)}
        >
            <div
                style={{
                    position: 'absolute',
                    background: hover ? GUIDE_CYAN_HOVER : GUIDE_CYAN,
                    ...line,
                }}
            />
            {hover && (
                <span
                    style={{
                        position: 'absolute',
                        whiteSpace: 'nowrap',
                        fontSize: 10,
                        lineHeight: 1.3,
                        padding: '2px 6px',
                        borderRadius: 4,
                        color: '#04121a',
                        background: 'rgba(0, 255, 255, 0.92)',
                        boxShadow: '0 2px 6px rgba(0, 0, 0, 0.4)',
                        pointerEvents: 'none',
                        zIndex: 2,
                        ...chip,
                    }}
                >
                    {label}
                </span>
            )}
        </div>
    );
};

const GuideOverlay = () => (
    <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
        {CL2K_GUIDES.map((g, i) => (
            <GuideLine key={`${g.o}${g.p}-${i}`} {...g} />
        ))}
    </div>
);

// Small "Show CL2K guides" checkbox used next to every poster preview.
const GuidesToggle = ({ show, onChange }) => (
    <label className="flex items-center gap-1.5 text-xs text-secondary cursor-pointer">
        <input type="checkbox" checked={show} onChange={e => onChange(e.target.checked)} />
        CL2K guides
    </label>
);

// ─── Logo selector (TMDB / fanart grid + custom upload) ─────────────────────

// A logo source picker shared by the render + uploaded-canvas flows. Pick a
// TMDB/fanart logo, or upload a custom PNG. A custom logo takes priority and
// hides the grid until removed; the chosen logo is whitened + placed on the CL2K
// guides by the backend (renderer._place_logo), so any source is CL2K-correct.
// `scale`/`onScale` (optional) expose the logo-size override: 1.0 = the strict
// CL2K guide box; raising it relaxes the height clamp so tall/boxy logos
// (sticker-style, < ~3:1 aspect) render readable instead of stamp-sized.
// `yOffset`/`onYOffset` (optional) shift the logo vertically (px from the locked
// baseline; positive = down) — the template treats the vertical as judgement,
// and hand-made posters hang oversized logos below the bottom guide.
const LogoSelector = ({
    label = 'Logo',
    logos = [],
    loading = false,
    selected,
    onSelect,
    customLogo,
    onCustomChange,
    scale,
    onScale,
    yOffset,
    onYOffset,
    whiten, // effective CL2K-whiten state (config default until overridden)
    onWhiten,
    touchUpUrl, // processed (un-flipped) logo for the B/W touch-up brush
    onFlipMask,
    emptyText = 'No logos from this source — a text wordmark is used as fallback.',
}) => {
    const [showTouchUp, setShowTouchUp] = useState(false);
    const onFile = e => {
        const f = e.target.files?.[0];
        e.target.value = ''; // allow re-selecting the same file
        if (!f) return;
        const reader = new FileReader();
        reader.onload = () =>
            onCustomChange({
                b64: String(reader.result).split(',').pop(),
                name: f.name,
                url: String(reader.result),
            });
        reader.readAsDataURL(f);
    };
    return (
        <div className="bg-surface border border-border rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-medium text-primary">{label}</h3>
                <div className="flex items-center gap-1.5">
                    {onWhiten && (
                        <>
                            <button
                                type="button"
                                className={`px-2.5 py-1 text-xs rounded-md border ${
                                    whiten
                                        ? 'bg-primary text-white border-primary'
                                        : 'bg-surface text-secondary border-border hover:border-border-strong'
                                }`}
                                onClick={() => onWhiten(true)}
                                title="CL2K two-tone: white fills, black keylines"
                            >
                                CL2K white
                            </button>
                            <button
                                type="button"
                                className={`px-2.5 py-1 text-xs rounded-md border ${
                                    !whiten
                                        ? 'bg-primary text-white border-primary'
                                        : 'bg-surface text-secondary border-border hover:border-border-strong'
                                }`}
                                onClick={() => onWhiten(false)}
                                title="Keep the logo's original colors"
                            >
                                Original
                            </button>
                        </>
                    )}
                    <label className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs border border-border text-secondary hover:border-border-strong cursor-pointer">
                        <span className="material-symbols-outlined text-sm">upload</span>
                        Upload custom
                        <input type="file" accept="image/*" className="hidden" onChange={onFile} />
                    </label>
                </div>
            </div>
            {customLogo ? (
                <div className="flex items-center gap-3 rounded-md border-2 border-primary bg-black p-2">
                    <img
                        src={customLogo.url}
                        alt="Custom logo"
                        className="h-14 w-auto max-w-[60%] object-contain"
                    />
                    <span className="flex-1 truncate text-xs text-secondary">
                        {customLogo.name}
                    </span>
                    <Button
                        onClick={() => onCustomChange(null)}
                        variant="secondary"
                        icon="close"
                        size="small"
                    >
                        Remove
                    </Button>
                </div>
            ) : loading ? (
                <div className="text-xs text-tertiary py-4">Loading…</div>
            ) : logos.length === 0 ? (
                <div className="text-xs text-tertiary py-2">{emptyText}</div>
            ) : (
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-72 overflow-auto">
                    {logos.map((it, idx) => {
                        const path = it.file_path;
                        const isSel = selected === path;
                        return (
                            <button
                                key={`${path}-${idx}`}
                                type="button"
                                onClick={() => onSelect(isSel ? null : path)}
                                aria-pressed={isSel}
                                className={`relative aspect-video rounded-md overflow-hidden border-2 bg-black transition-all ${
                                    isSel
                                        ? 'border-primary ring-2 ring-primary/40'
                                        : 'border-border hover:border-border-strong'
                                }`}
                                title={it.width ? `${it.width}×${it.height}` : path}
                            >
                                <img
                                    src={it.url || urlForPath(path)}
                                    alt=""
                                    loading="lazy"
                                    className="absolute inset-0 w-full h-full object-contain"
                                />
                                {isSel && (
                                    <span className="absolute top-1 right-1 inline-flex items-center justify-center w-5 h-5 rounded-full bg-primary text-white">
                                        <span className="material-symbols-outlined text-sm">
                                            check
                                        </span>
                                    </span>
                                )}
                            </button>
                        );
                    })}
                </div>
            )}
            {onScale && (
                <label className="mt-2 flex items-center gap-2 text-xs text-secondary">
                    <span className="w-24">Logo size</span>
                    <input
                        type="range"
                        min="50"
                        max="250"
                        step="5"
                        value={Math.round((scale ?? 1) * 100)}
                        onChange={e => onScale(Number(e.target.value) / 100)}
                        className="flex-1"
                    />
                    <span className="w-10 text-right">{Math.round((scale ?? 1) * 100)}%</span>
                </label>
            )}
            {onYOffset && (
                <label className="mt-2 flex items-center gap-2 text-xs text-secondary">
                    <span className="w-24">Logo position</span>
                    <input
                        type="range"
                        min="-300"
                        max="100"
                        step="5"
                        value={yOffset ?? 0}
                        onChange={e => onYOffset(Number(e.target.value))}
                        className="flex-1"
                    />
                    <span className="w-10 text-right">
                        {(yOffset ?? 0) > 0 ? `+${yOffset}` : (yOffset ?? 0)}
                    </span>
                </label>
            )}
            {/* B/W touch-up: a global two-tone map can't decide interior accents
                that share saturation + luma with their surroundings — brush those
                regions to flip black↔white. Drawn over the UN-flipped processed
                logo so the accumulated strokes stay valid; the live overlay and
                the render apply the flip. */}
            {onFlipMask && touchUpUrl && whiten && (
                <div className="mt-2">
                    <button
                        type="button"
                        onClick={() => setShowTouchUp(s => !s)}
                        className="px-2.5 py-1 text-xs rounded-md border bg-surface text-secondary border-border hover:border-border-strong"
                    >
                        {showTouchUp ? 'Hide colour fix' : 'Fix a mis-coloured area (optional)'}
                    </button>
                    {showTouchUp && (
                        <div className="mt-2">
                            <p className="text-xs text-tertiary mb-1">
                                <span className="text-secondary">
                                    Most logos whiten correctly — you can skip this.
                                </span>{' '}
                                Only if a part came out the wrong shade (a black area that should be
                                white, or vice-versa), brush over just those spots to flip them.
                                Everything you don&apos;t paint is left exactly as shown. Applies to
                                the preview and the saved poster.
                            </p>
                            <div className="bg-black rounded p-1 inline-block max-w-full">
                                <BrushMask
                                    imageUrl={touchUpUrl}
                                    brushSize={10}
                                    onMaskChange={onFlipMask}
                                />
                            </div>
                        </div>
                    )}
                </div>
            )}
            <p className="mt-2 text-xs text-tertiary">
                Whitened, trimmed and placed on the CL2K guides automatically — it moves live in the
                preview as you drag.
                {onScale && (
                    <>
                        {' '}
                        Size 100% = the CL2K guide box; raise it to enlarge past the 600px guide
                        (hand-made posters run up to ~880px wide) — capped only by the canvas.
                    </>
                )}
                {onYOffset && (
                    <>
                        {' '}
                        Position 0 = the locked baseline; negative moves the logo up, positive down
                        (hand-made posters hang tall logos ~30–50 below).
                    </>
                )}{' '}
                {((onScale && Math.round((scale ?? 1) * 100) !== 100) ||
                    (onYOffset && (yOffset ?? 0) !== 0)) && (
                    <button
                        type="button"
                        onClick={() => {
                            if (onScale) onScale(1);
                            if (onYOffset) onYOffset(0);
                        }}
                        className="text-primary underline hover:no-underline"
                    >
                        Reset to CL2K defaults
                    </button>
                )}
            </p>
        </div>
    );
};

// ─── Square art tab ─────────────────────────────────────────────────────────

// Drag a 1:1 cover-crop box over the source art to choose what fills the square.
const SquareFramer = ({
    imageUrl,
    focusX,
    focusY,
    onChange,
    fitMode,
    setFitMode,
    zoom,
    setZoom,
    aspect = 1, // target frame h/w: 1 = square, 9/16 = background art
    title = 'Crop to square',
    frameName = '1:1 square',
}) => {
    const wrapRef = useRef(null);
    const [ratio, setRatio] = useState(null); // natural h/w
    const dragging = useRef(false);
    // The kept region (fraction of the source shown in the target frame) under the
    // current Fill/Fit + zoom — mirrors render_framed_art's scale+pan maths.
    const rect = useMemo(() => {
        if (!ratio) return null;
        const z = Math.max(0.5, Math.min(zoom || 1, 3));
        // frame width = 1, height = aspect; source width = 1, height = ratio (h/w).
        const base = fitMode === 'fit' ? Math.min(1, aspect / ratio) : Math.max(1, aspect / ratio);
        const s = base * z;
        const nw = s; // scaled source width (frame width = 1)
        const nh = ratio * s; // scaled source height
        const wF = Math.min(1, 1 / nw);
        const hF = Math.min(1, aspect / nh);
        return {
            left: Math.max(0, Math.min(focusX - wF / 2, 1 - wF)),
            top: Math.max(0, Math.min(focusY - hF / 2, 1 - hF)),
            w: wF,
            h: hF,
        };
    }, [ratio, focusX, focusY, fitMode, zoom, aspect]);
    const segCls = on =>
        `px-2.5 py-1 text-sm rounded-md border ${
            on
                ? 'bg-primary text-white border-primary'
                : 'bg-surface text-secondary border-border hover:border-border-strong'
        }`;
    const point = useCallback(e => {
        const el = wrapRef.current;
        if (!el) return null;
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) return null;
        const cx = (e.touches?.[0]?.clientX ?? e.clientX) - r.left;
        const cy = (e.touches?.[0]?.clientY ?? e.clientY) - r.top;
        return { nx: clamp01(cx / r.width), ny: clamp01(cy / r.height) };
    }, []);
    const down = useCallback(
        e => {
            e.preventDefault();
            dragging.current = true;
            const p = point(e);
            if (p) onChange(p.nx, p.ny);
        },
        [point, onChange]
    );
    const move = useCallback(
        e => {
            if (!dragging.current) return;
            const p = point(e);
            if (p) onChange(p.nx, p.ny);
        },
        [point, onChange]
    );
    const up = useCallback(() => {
        dragging.current = false;
    }, []);
    return (
        <div className="bg-surface border border-border rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-medium text-primary">{title}</h3>
                <div className="flex items-center gap-1">
                    <button
                        type="button"
                        className={segCls(fitMode !== 'fit')}
                        onClick={() => setFitMode('cover')}
                    >
                        Fill
                    </button>
                    <button
                        type="button"
                        className={segCls(fitMode === 'fit')}
                        onClick={() => setFitMode('fit')}
                    >
                        Fit
                    </button>
                    <Button
                        onClick={() => {
                            onChange(0.5, 0.5);
                            setZoom(1);
                        }}
                        variant="secondary"
                        icon="filter_center_focus"
                        size="small"
                    >
                        Reset
                    </Button>
                </div>
            </div>
            <p className="text-xs text-tertiary mb-2">
                {fitMode === 'fit'
                    ? 'Fit shows the whole image on black. Zoom in to fill more; drag to pan when zoomed.'
                    : `Fill crops to the ${frameName} — drag to choose what stays. Zoom to punch in tighter.`}
            </p>
            <label className="flex items-center gap-2 text-xs text-secondary mb-2">
                <span className="w-12 shrink-0">Zoom</span>
                <input
                    type="range"
                    min="0.5"
                    max="3"
                    step="0.05"
                    value={zoom ?? 1}
                    onChange={e => setZoom(Number(e.target.value))}
                    className="flex-1"
                />
                <span className="w-12 shrink-0 text-right text-tertiary">
                    {(zoom ?? 1).toFixed(2)}×
                </span>
            </label>
            <div
                ref={wrapRef}
                className="relative inline-block leading-none select-none overflow-hidden rounded cursor-crosshair max-w-full"
                onMouseDown={down}
                onMouseMove={move}
                onMouseUp={up}
                onMouseLeave={up}
                onTouchStart={down}
                onTouchMove={move}
                onTouchEnd={up}
            >
                <img
                    src={imageUrl}
                    alt={title}
                    onLoad={e =>
                        setRatio(
                            e.target.naturalWidth
                                ? e.target.naturalHeight / e.target.naturalWidth
                                : null
                        )
                    }
                    className="block max-w-full"
                    draggable={false}
                />
                {rect && (
                    <div
                        className="absolute border-2 border-primary"
                        style={{
                            left: `${rect.left * 100}%`,
                            top: `${rect.top * 100}%`,
                            width: `${rect.w * 100}%`,
                            height: `${rect.h * 100}%`,
                            boxShadow: '0 0 0 9999px rgba(0,0,0,0.5)',
                            pointerEvents: 'none',
                        }}
                    />
                )}
            </div>
        </div>
    );
};

// Season selector for the asset makers: file the art for ONE season of a show
// (` - Season NN` naming; Plex seasons take background/square art and Kometa
// reads Season##_background). Blank = the show itself. Hidden for movies and
// collections (no seasons to target).
const AssetSeasonField = ({ show, value, onChange }) => {
    if (!show) return null;
    return (
        <label className="flex items-center gap-2 text-sm text-secondary">
            <span className="w-28">Season</span>
            <input
                type="number"
                min="0"
                max="99"
                value={value}
                onChange={e => onChange(e.target.value)}
                placeholder="blank = the show itself"
                className="flex-1 bg-surface border border-border rounded px-2 py-1 text-sm text-primary"
            />
        </label>
    );
};

const seasonSuffix = seasonNum =>
    seasonNum === null
        ? ''
        : seasonNum === 0
          ? ' - Specials'
          : ` - Season ${String(seasonNum).padStart(2, '0')}`;

// One-line workflow reminder shared by the asset-maker Output cards: a generated
// file only reaches Plex/Kometa once Asset Renamerr runs over it, and it can only
// see the file if the maker's output_dir is one of Poster Renamerr's source_dirs.
const AssetWorkflowHint = () => (
    <p className="text-xs text-tertiary">
        Applies on the next Asset Renamerr run — the CL2K output directory must be one of Poster
        Renamerr&apos;s source dirs for the file to be scanned.
    </p>
);

const SquareArtPanel = ({ item, backdrops, loadingArt, saveTargets, toast }) => {
    const [backdrop, setBackdrop] = useState(null); // file_path | url
    const [customBg, setCustomBg] = useState(null); // { b64, url, name }
    const [focusX, setFocusX] = useState(0.5);
    const [focusY, setFocusY] = useState(0.5);
    const [fitMode, setFitMode] = useState('cover'); // cover (fill) | fit (contain)
    const [zoom, setZoom] = useState(1);
    const [seasonNumber, setSeasonNumber] = useState(''); // '' = show-level asset
    const [previewUrl, setPreviewUrl] = useState(null);
    const [previewing, setPreviewing] = useState(false);
    const [busy, setBusy] = useState(false);

    const srcUrl = customBg?.url || (backdrop ? urlForPath(backdrop) : null);
    const hasSrc = !!(customBg || backdrop);
    const seasonNum = item.kind === 'show' && seasonNumber !== '' ? Number(seasonNumber) : null;

    const req = useMemo(
        () => ({
            kind: item.kind,
            title: item.title,
            tmdb_id: item.tmdb_id,
            year: item.year,
            tvdb_id: item.tvdb_id,
            imdb_id: item.imdb_id,
            season_number: seasonNum,
            backdrop_path: customBg ? null : backdrop,
            backdrop_b64: customBg?.b64 || null,
            focus_x: focusX,
            focus_y: focusY,
            fit_mode: fitMode,
            zoom,
            save_local: saveTargets.saveLocal,
            upload_gdrive: saveTargets.uploadGdrive,
        }),
        [
            item,
            backdrop,
            customBg,
            focusX,
            focusY,
            fitMode,
            zoom,
            seasonNum,
            saveTargets.saveLocal,
            saveTargets.uploadGdrive,
        ]
    );
    const reqRef = useRef(req);
    useEffect(() => {
        reqRef.current = req;
    }, [req]);

    const sig = `${customBg?.b64?.slice(0, 32) || backdrop}|${focusX}|${focusY}|${fitMode}|${zoom}`;
    useEffect(() => {
        if (!hasSrc) return undefined;
        let cancelled = false;
        const t = setTimeout(async () => {
            setPreviewing(true);
            try {
                const blob = await cl2kMakerAPI.squarePreview(reqRef.current);
                if (!cancelled)
                    setPreviewUrl(prev => {
                        if (prev) URL.revokeObjectURL(prev);
                        return URL.createObjectURL(blob);
                    });
            } catch {
                /* quiet — the source may be unset mid-change */
            } finally {
                if (!cancelled) setPreviewing(false);
            }
        }, 450);
        return () => {
            cancelled = true;
            clearTimeout(t);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [sig]);
    useEffect(
        () => () => {
            if (previewUrl) URL.revokeObjectURL(previewUrl);
        },
        [previewUrl]
    );

    const onFile = e => {
        const f = e.target.files?.[0];
        e.target.value = '';
        if (!f) return;
        const reader = new FileReader();
        reader.onload = () => {
            const url = String(reader.result);
            setCustomBg({ b64: url.split(',').pop(), url, name: f.name });
            setBackdrop(null);
        };
        reader.readAsDataURL(f);
    };

    const onGenerate = async () => {
        setBusy(true);
        try {
            const resp = await cl2kMakerAPI.squareGenerate(req);
            savedToast(toast, resp?.data, 'Square art generated');
        } catch (err) {
            toast.error(err.message || 'Generate failed');
        } finally {
            setBusy(false);
        }
    };

    return (
        <section className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="flex flex-col gap-4">
                <div className="bg-surface border border-border rounded-lg p-3">
                    <div className="flex items-center justify-between mb-2">
                        <h3 className="text-sm font-medium text-primary">Source art (backdrop)</h3>
                        <label className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs border border-border text-secondary hover:border-border-strong cursor-pointer">
                            <span className="material-symbols-outlined text-sm">upload</span>
                            Upload
                            <input
                                type="file"
                                accept="image/*"
                                className="hidden"
                                onChange={onFile}
                            />
                        </label>
                    </div>
                    {customBg ? (
                        <div className="flex items-center gap-3 rounded-md border-2 border-primary bg-surface-alt p-2">
                            <img
                                src={customBg.url}
                                alt="Uploaded source"
                                className="h-16 w-auto max-w-[60%] object-contain rounded"
                            />
                            <span className="flex-1 truncate text-xs text-secondary">
                                {customBg.name}
                            </span>
                            <Button
                                onClick={() => setCustomBg(null)}
                                variant="secondary"
                                icon="close"
                                size="small"
                            >
                                Remove
                            </Button>
                        </div>
                    ) : (
                        <Picker
                            label=""
                            items={backdrops}
                            loading={loadingArt}
                            selected={backdrop}
                            onSelect={p => setBackdrop(p)}
                            aspect="aspect-video"
                            emptyText="No backdrops from TMDB/fanart — upload one above."
                        />
                    )}
                </div>

                {srcUrl && (
                    <SquareFramer
                        imageUrl={srcUrl}
                        focusX={focusX}
                        focusY={focusY}
                        onChange={(fx, fy) => {
                            setFocusX(fx);
                            setFocusY(fy);
                        }}
                        fitMode={fitMode}
                        setFitMode={setFitMode}
                        zoom={zoom}
                        setZoom={setZoom}
                    />
                )}
            </div>

            <div className="flex flex-col gap-3 self-start sticky top-4 max-h-screen overflow-y-auto">
                <div className="bg-surface border border-border rounded-lg p-3">
                    <h3 className="text-sm font-medium text-primary mb-2">Preview (1000×1000)</h3>
                    <div className="relative aspect-square bg-black rounded overflow-hidden flex items-center justify-center">
                        {hasSrc && previewUrl ? (
                            <img
                                src={previewUrl}
                                alt="Square art preview"
                                className="w-full h-full object-contain"
                            />
                        ) : (
                            <span className="text-xs text-tertiary px-4 text-center">
                                {hasSrc ? 'Rendering preview…' : 'Pick or upload source art.'}
                            </span>
                        )}
                    </div>
                </div>
                <div className="bg-surface border border-border rounded-lg p-3 flex flex-col gap-2">
                    <h3 className="text-sm font-medium text-primary">Output</h3>
                    <AssetSeasonField
                        show={item.kind === 'show'}
                        value={seasonNumber}
                        onChange={setSeasonNumber}
                    />
                    <p className="text-xs text-tertiary">
                        Saved as{' '}
                        <span className="text-secondary">
                            Title (Year) {'{ids}'}
                            {seasonSuffix(seasonNum)} - SquareArt.jpg
                        </span>{' '}
                        and applied to Plex via Asset Renamerr (square art is Plex-direct only).
                    </p>
                    <AssetWorkflowHint />
                    <SaveTargets targets={saveTargets} />
                    <LoadingButton
                        onClick={onGenerate}
                        loading={busy || previewing}
                        disabled={!hasSrc || saveTargets.noTarget}
                        icon="save"
                    >
                        Generate &amp; save
                    </LoadingButton>
                </div>
            </div>
        </section>
    );
};

// ─── Background art tab ─────────────────────────────────────────────────────

const BackgroundArtPanel = ({ item, backdrops, loadingArt, saveTargets, toast }) => {
    const [backdrop, setBackdrop] = useState(null); // file_path | url
    const [customBg, setCustomBg] = useState(null); // { b64, url, name }
    const [focusX, setFocusX] = useState(0.5);
    const [focusY, setFocusY] = useState(0.5);
    const [fitMode, setFitMode] = useState('cover'); // cover (fill) | fit (contain)
    const [zoom, setZoom] = useState(1);
    const [resolution, setResolution] = useState('1080p'); // 1080p | 4k (Plex dims)
    const [seasonNumber, setSeasonNumber] = useState(''); // '' = show-level asset
    const [previewUrl, setPreviewUrl] = useState(null);
    const [previewing, setPreviewing] = useState(false);
    const [busy, setBusy] = useState(false);

    const srcUrl = customBg?.url || (backdrop ? urlForPath(backdrop) : null);
    const hasSrc = !!(customBg || backdrop);
    const seasonNum = item.kind === 'show' && seasonNumber !== '' ? Number(seasonNumber) : null;

    const req = useMemo(
        () => ({
            kind: item.kind,
            title: item.title,
            tmdb_id: item.tmdb_id,
            year: item.year,
            tvdb_id: item.tvdb_id,
            imdb_id: item.imdb_id,
            season_number: seasonNum,
            backdrop_path: customBg ? null : backdrop,
            backdrop_b64: customBg?.b64 || null,
            focus_x: focusX,
            focus_y: focusY,
            fit_mode: fitMode,
            zoom,
            resolution,
            save_local: saveTargets.saveLocal,
            upload_gdrive: saveTargets.uploadGdrive,
        }),
        [
            item,
            backdrop,
            customBg,
            focusX,
            focusY,
            fitMode,
            zoom,
            resolution,
            seasonNum,
            saveTargets.saveLocal,
            saveTargets.uploadGdrive,
        ]
    );
    const reqRef = useRef(req);
    useEffect(() => {
        reqRef.current = req;
    }, [req]);

    // Preview renders at 1080p regardless of resolution — same 16:9 frame.
    const sig = `${customBg?.b64?.slice(0, 32) || backdrop}|${focusX}|${focusY}|${fitMode}|${zoom}`;
    useEffect(() => {
        if (!hasSrc) return undefined;
        let cancelled = false;
        const t = setTimeout(async () => {
            setPreviewing(true);
            try {
                const blob = await cl2kMakerAPI.backgroundPreview(reqRef.current);
                if (!cancelled)
                    setPreviewUrl(prev => {
                        if (prev) URL.revokeObjectURL(prev);
                        return URL.createObjectURL(blob);
                    });
            } catch {
                /* quiet — the source may be unset mid-change */
            } finally {
                if (!cancelled) setPreviewing(false);
            }
        }, 450);
        return () => {
            cancelled = true;
            clearTimeout(t);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [sig]);
    useEffect(
        () => () => {
            if (previewUrl) URL.revokeObjectURL(previewUrl);
        },
        [previewUrl]
    );

    const onFile = e => {
        const f = e.target.files?.[0];
        e.target.value = '';
        if (!f) return;
        const reader = new FileReader();
        reader.onload = () => {
            const url = String(reader.result);
            setCustomBg({ b64: url.split(',').pop(), url, name: f.name });
            setBackdrop(null);
        };
        reader.readAsDataURL(f);
    };

    const onGenerate = async () => {
        setBusy(true);
        try {
            const resp = await cl2kMakerAPI.backgroundGenerate(req);
            savedToast(toast, resp?.data, 'Background art generated');
        } catch (err) {
            toast.error(err.message || 'Generate failed');
        } finally {
            setBusy(false);
        }
    };

    const resCls = on =>
        `px-2.5 py-1 text-sm rounded-md border ${
            on
                ? 'bg-primary text-white border-primary'
                : 'bg-surface text-secondary border-border hover:border-border-strong'
        }`;

    return (
        <section className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="flex flex-col gap-4">
                <div className="bg-surface border border-border rounded-lg p-3">
                    <div className="flex items-center justify-between mb-2">
                        <h3 className="text-sm font-medium text-primary">Source art (backdrop)</h3>
                        <label className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs border border-border text-secondary hover:border-border-strong cursor-pointer">
                            <span className="material-symbols-outlined text-sm">upload</span>
                            Upload
                            <input
                                type="file"
                                accept="image/*"
                                className="hidden"
                                onChange={onFile}
                            />
                        </label>
                    </div>
                    {customBg ? (
                        <div className="flex items-center gap-3 rounded-md border-2 border-primary bg-surface-alt p-2">
                            <img
                                src={customBg.url}
                                alt="Uploaded source"
                                className="h-16 w-auto max-w-[60%] object-contain rounded"
                            />
                            <span className="flex-1 truncate text-xs text-secondary">
                                {customBg.name}
                            </span>
                            <Button
                                onClick={() => setCustomBg(null)}
                                variant="secondary"
                                icon="close"
                                size="small"
                            >
                                Remove
                            </Button>
                        </div>
                    ) : (
                        <Picker
                            label=""
                            items={backdrops}
                            loading={loadingArt}
                            selected={backdrop}
                            onSelect={p => setBackdrop(p)}
                            aspect="aspect-video"
                            emptyText="No backdrops from TMDB/fanart — upload one above."
                        />
                    )}
                </div>

                {srcUrl && (
                    <SquareFramer
                        imageUrl={srcUrl}
                        focusX={focusX}
                        focusY={focusY}
                        onChange={(fx, fy) => {
                            setFocusX(fx);
                            setFocusY(fy);
                        }}
                        fitMode={fitMode}
                        setFitMode={setFitMode}
                        zoom={zoom}
                        setZoom={setZoom}
                        aspect={9 / 16}
                        title="Crop to 16:9"
                        frameName="16:9 frame"
                    />
                )}
            </div>

            <div className="flex flex-col gap-3 self-start sticky top-4 max-h-screen overflow-y-auto">
                <div className="bg-surface border border-border rounded-lg p-3">
                    <div className="flex items-center justify-between mb-2">
                        <h3 className="text-sm font-medium text-primary">
                            Preview ({resolution === '4k' ? '3840×2160' : '1920×1080'})
                        </h3>
                        <div className="flex items-center gap-1">
                            <button
                                type="button"
                                className={resCls(resolution !== '4k')}
                                onClick={() => setResolution('1080p')}
                            >
                                1080p
                            </button>
                            <button
                                type="button"
                                className={resCls(resolution === '4k')}
                                onClick={() => setResolution('4k')}
                            >
                                4K
                            </button>
                        </div>
                    </div>
                    <div className="relative aspect-video bg-black rounded overflow-hidden flex items-center justify-center">
                        {hasSrc && previewUrl ? (
                            <img
                                src={previewUrl}
                                alt="Background art preview"
                                className="w-full h-full object-contain"
                            />
                        ) : (
                            <span className="text-xs text-tertiary px-4 text-center">
                                {hasSrc ? 'Rendering preview…' : 'Pick or upload source art.'}
                            </span>
                        )}
                    </div>
                </div>
                <div className="bg-surface border border-border rounded-lg p-3 flex flex-col gap-2">
                    <h3 className="text-sm font-medium text-primary">Output</h3>
                    <AssetSeasonField
                        show={item.kind === 'show'}
                        value={seasonNumber}
                        onChange={setSeasonNumber}
                    />
                    <p className="text-xs text-tertiary">
                        Saved as{' '}
                        <span className="text-secondary">
                            Title (Year) {'{ids}'}
                            {seasonSuffix(seasonNum)} - Background.jpg
                        </span>{' '}
                        and applied to Plex/Kometa via Asset Renamerr.
                    </p>
                    <AssetWorkflowHint />
                    <SaveTargets targets={saveTargets} />
                    <LoadingButton
                        onClick={onGenerate}
                        loading={busy || previewing}
                        disabled={!hasSrc || saveTargets.noTarget}
                        icon="save"
                    >
                        Generate &amp; save
                    </LoadingButton>
                </div>
            </div>
        </section>
    );
};

// ─── Logo asset tab ─────────────────────────────────────────────────────────

const LogoAssetPanel = ({ item, logos, loadingArt, saveTargets, toast }) => {
    const [logo, setLogo] = useState(null); // file_path
    const [customLogo, setCustomLogo] = useState(null); // { b64, url, name }
    const [whiten, setWhiten] = useState(false);
    const [previewUrl, setPreviewUrl] = useState(null); // UN-flipped (brush base)
    const [previewing, setPreviewing] = useState(false);
    const [busy, setBusy] = useState(false);
    const hasLogo = !!(logo || customLogo);

    // B/W touch-up strokes are keyed to the (logo, whiten) they were drawn over
    // so a stale mask becomes a derived no-op (same pattern as the Builder).
    const flipKey = `${customLogo?.b64?.slice(0, 32) || logo}|${whiten}`;
    const [flip, setFlip] = useState(null); // { key, b64 }
    const flipB64 = flip && flip.key === flipKey ? flip.b64 : null;
    const setFlipB64 = useCallback(b64 => setFlip(b64 ? { key: flipKey, b64 } : null), [flipKey]);
    const [showTouchUp, setShowTouchUp] = useState(false);
    const [flipped, setFlipped] = useState(null); // { forB64, url } — flipped preview

    const setCustomExclusive = useCallback(c => {
        setCustomLogo(c);
        if (c) setLogo(null);
    }, []);

    const req = useMemo(
        () => ({
            kind: item.kind,
            title: item.title,
            tmdb_id: item.tmdb_id,
            year: item.year,
            tvdb_id: item.tvdb_id,
            imdb_id: item.imdb_id,
            logo_path: customLogo ? null : logo,
            logo_b64: customLogo?.b64 || null,
            whiten,
            flip_b64: flipB64,
            save_local: saveTargets.saveLocal,
            upload_gdrive: saveTargets.uploadGdrive,
        }),
        [item, logo, customLogo, whiten, flipB64, saveTargets.saveLocal, saveTargets.uploadGdrive]
    );
    const reqRef = useRef(req);
    useEffect(() => {
        reqRef.current = req;
    }, [req]);

    // Brush base: the processed logo WITHOUT the flip — it must stay stable as
    // strokes land, or the accumulated mask would be drawn over a moving target.
    const sig = `${customLogo?.b64?.slice(0, 32) || logo}|${whiten}`;
    useEffect(() => {
        if (!hasLogo) return undefined;
        let cancelled = false;
        const t = setTimeout(async () => {
            setPreviewing(true);
            try {
                const blob = await cl2kMakerAPI.logoAssetPreview({
                    ...reqRef.current,
                    flip_b64: null,
                });
                if (!cancelled)
                    setPreviewUrl(prev => {
                        if (prev) URL.revokeObjectURL(prev);
                        return URL.createObjectURL(blob);
                    });
            } catch {
                /* quiet */
            } finally {
                if (!cancelled) setPreviewing(false);
            }
        }, 300);
        return () => {
            cancelled = true;
            clearTimeout(t);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [sig]);
    useEffect(
        () => () => {
            if (previewUrl) URL.revokeObjectURL(previewUrl);
        },
        [previewUrl]
    );
    // Flipped variant for the preview box (and what Export files).
    useEffect(() => {
        if (!flipB64) return undefined;
        let cancelled = false;
        (async () => {
            try {
                const blob = await cl2kMakerAPI.logoAssetPreview(reqRef.current);
                if (!cancelled)
                    setFlipped(prev => {
                        if (prev?.url) URL.revokeObjectURL(prev.url);
                        return { forB64: flipB64, url: URL.createObjectURL(blob) };
                    });
            } catch {
                /* quiet — the base preview still shows */
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [flipB64]);
    useEffect(
        () => () => {
            if (flipped?.url) URL.revokeObjectURL(flipped.url);
        },
        [flipped]
    );
    const displayUrl = flipB64 && flipped?.forB64 === flipB64 ? flipped.url : previewUrl;

    const onExport = async () => {
        setBusy(true);
        try {
            const resp = await cl2kMakerAPI.logoAssetGenerate(req);
            savedToast(toast, resp?.data, 'Logo filed');
        } catch (err) {
            toast.error(err.message || 'Export failed');
        } finally {
            setBusy(false);
        }
    };

    const seg = on =>
        `px-3 py-1 text-sm rounded-md border ${
            on
                ? 'bg-primary text-white border-primary'
                : 'bg-surface text-secondary border-border hover:border-border-strong'
        }`;

    return (
        <section className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="flex flex-col gap-4">
                <LogoSelector
                    label="Logo (TMDB / fanart / custom)"
                    logos={logos}
                    loading={loadingArt}
                    selected={logo}
                    onSelect={setLogo}
                    customLogo={customLogo}
                    onCustomChange={setCustomExclusive}
                    emptyText="No logos from TMDB/fanart — upload a custom PNG."
                />
                <div className="bg-surface border border-border rounded-lg p-3">
                    <h3 className="text-sm font-medium text-primary mb-2">Colour</h3>
                    <div className="flex items-center gap-2">
                        <button
                            type="button"
                            className={seg(!whiten)}
                            onClick={() => setWhiten(false)}
                        >
                            Original
                        </button>
                        <button
                            type="button"
                            className={seg(whiten)}
                            onClick={() => setWhiten(true)}
                        >
                            CL2K white
                        </button>
                    </div>
                    <p className="text-xs text-tertiary mt-2">
                        Original keeps the clear logo&apos;s colours (the usual Plex/Kometa logo
                        asset). CL2K white recolours it to the CL2K two-tone — white fills, black
                        keylines — like a CL2K poster logo.
                    </p>
                    {/* B/W touch-up: flip the regions the automatic two-tone got wrong.
                        Drawn over the UN-flipped preview so strokes stay valid. */}
                    {whiten && hasLogo && previewUrl && (
                        <div className="mt-2">
                            <button
                                type="button"
                                onClick={() => setShowTouchUp(s => !s)}
                                className="px-2.5 py-1 text-xs rounded-md border bg-surface text-secondary border-border hover:border-border-strong"
                            >
                                {showTouchUp
                                    ? 'Hide colour fix'
                                    : 'Fix a mis-coloured area (optional)'}
                            </button>
                            {showTouchUp && (
                                <div className="mt-2">
                                    <p className="text-xs text-tertiary mb-1">
                                        <span className="text-secondary">
                                            Most logos whiten correctly — you can skip this.
                                        </span>{' '}
                                        Only if a part came out the wrong shade, brush over just
                                        those spots to flip them black↔white. Everything you
                                        don&apos;t paint is left exactly as shown.
                                    </p>
                                    <div className="bg-black rounded p-1 inline-block max-w-full">
                                        <BrushMask
                                            imageUrl={previewUrl}
                                            brushSize={10}
                                            onMaskChange={setFlipB64}
                                        />
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>

            <div className="flex flex-col gap-3 self-start sticky top-4 max-h-screen overflow-y-auto">
                <div className="bg-surface border border-border rounded-lg p-3">
                    <h3 className="text-sm font-medium text-primary mb-2">Preview</h3>
                    <div
                        className="relative aspect-video rounded overflow-hidden flex items-center justify-center"
                        style={{
                            backgroundImage:
                                'repeating-conic-gradient(#3a3a4a 0% 25%, #2a2a38 0% 50%)',
                            backgroundSize: '22px 22px',
                        }}
                    >
                        {hasLogo && displayUrl ? (
                            <img
                                src={displayUrl}
                                alt="Logo preview"
                                className="max-w-[90%] max-h-[90%] object-contain"
                            />
                        ) : (
                            <span className="text-xs text-tertiary px-4 text-center bg-black/40 rounded px-2 py-1">
                                {hasLogo ? 'Rendering preview…' : 'Pick or upload a logo.'}
                            </span>
                        )}
                    </div>
                </div>
                <div className="bg-surface border border-border rounded-lg p-3 flex flex-col gap-2">
                    <h3 className="text-sm font-medium text-primary">Output</h3>
                    <p className="text-xs text-tertiary">
                        Filed as{' '}
                        <span className="text-secondary">Title (Year) {'{ids}'} - Logo.png</span>{' '}
                        and applied to Plex/Kometa via Asset Renamerr — separate from any square
                        art.
                    </p>
                    <AssetWorkflowHint />
                    <SaveTargets targets={saveTargets} />
                    <LoadingButton
                        onClick={onExport}
                        loading={busy || previewing}
                        disabled={!hasLogo || saveTargets.noTarget}
                        icon="save"
                    >
                        Export &amp; save logo
                    </LoadingButton>
                </div>
            </div>
        </section>
    );
};

// ─── Upload finished-poster tab ─────────────────────────────────────────────

const UploadPosterPanel = ({
    item,
    effectiveKind,
    logos,
    loadingArt,
    config,
    saveTargets,
    toast,
}) => {
    const [file, setFile] = useState(null);
    const [busy, setBusy] = useState(false);
    const [addBorder, setAddBorder] = useState(true);
    // Per-render whiten override; null = the module config (whiten_logo) — the
    // FormData builder skips nulls so the backend falls back to the config.
    const [whitenLogo, setWhitenLogo] = useState(null);
    const effectiveWhiten = whitenLogo === null ? (config?.whiten_logo ?? true) : whitenLogo;
    const [logo, setLogo] = useState(null); // chosen TMDB/fanart logo file_path
    const [customLogo, setCustomLogo] = useState(null); // { b64, name, url }
    const [previewB64, setPreviewB64] = useState(null); // server-rendered preview
    const [previewing, setPreviewing] = useState(false);
    const [logoScale, setLogoScale] = useState(1);
    const [logoYOffset, setLogoYOffset] = useState(0);
    const [showGuides, setShowGuides] = useState(false);
    const localUrl = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
    useEffect(() => () => localUrl && URL.revokeObjectURL(localUrl), [localUrl]);

    // Any input that affects the render also drops a stale server preview, so the
    // shown image never misrepresents the current logo/border.
    const onCustomLogo = useCallback(c => {
        setCustomLogo(c);
        setPreviewB64(null);
        if (c) setLogo(null);
    }, []);
    const onLogoScale = useCallback(s => {
        setLogoScale(s);
        setPreviewB64(null);
    }, []);
    const onLogoYOffset = useCallback(y => {
        setLogoYOffset(y);
        setPreviewB64(null);
    }, []);
    const onPickLogo = useCallback(p => {
        setLogo(p);
        setPreviewB64(null);
    }, []);
    const onPickFile = useCallback(f => {
        setFile(f);
        setPreviewB64(null);
    }, []);
    const onToggleBorder = useCallback(v => {
        setAddBorder(v);
        setPreviewB64(null);
    }, []);

    const meta = useMemo(
        () => ({
            kind: effectiveKind,
            title: item.title,
            tmdb_id: item.tmdb_id,
            year: item.year,
            tvdb_id: item.tvdb_id,
            imdb_id: item.imdb_id,
            border: addBorder,
            logo_path: customLogo ? null : logo,
            logo_b64: customLogo?.b64 || null,
            logo_scale: logoScale,
            logo_y_offset: logoYOffset,
            whiten: whitenLogo,
        }),
        [effectiveKind, item, addBorder, logo, customLogo, logoScale, logoYOffset, whitenLogo]
    );

    const runPreview = useCallback(async () => {
        if (!file) return;
        setPreviewing(true);
        try {
            const resp = await cl2kMakerAPI.uploadPoster(file, { ...meta, preview: true });
            setPreviewB64(resp?.data?.preview_b64 || null);
        } catch (err) {
            toast.error(err.message || 'Preview failed');
        } finally {
            setPreviewing(false);
        }
    }, [file, meta, toast]);

    const submit = useCallback(async () => {
        if (!file) return;
        setBusy(true);
        try {
            const resp = await cl2kMakerAPI.uploadPoster(file, {
                ...meta,
                ...saveTargets.fields,
            });
            savedToast(toast, resp?.data);
        } catch (err) {
            toast.error(err.message || 'Save failed');
        } finally {
            setBusy(false);
        }
    }, [file, meta, saveTargets.fields, toast]);

    const shownSrc = previewB64 ? `data:image/jpeg;base64,${previewB64}` : localUrl;

    return (
        <section className="mt-4 bg-surface border border-border rounded-lg p-4 flex flex-col gap-3">
            <h3 className="text-sm font-medium text-primary">Finished poster → file</h3>
            <p className="text-xs text-tertiary">
                Upload a complete poster. It&apos;s DAPS-named and registered so the rest of CHUB
                picks it up. Optionally drop a logo onto it — leave the logo unset to store the
                poster unchanged.
            </p>
            <input
                type="file"
                accept="image/*"
                onChange={e => onPickFile(e.target.files?.[0] || null)}
            />
            {shownSrc && (
                <div className="flex flex-col gap-1" style={{ alignItems: 'flex-start' }}>
                    <div style={{ position: 'relative', display: 'inline-block' }}>
                        <img
                            src={shownSrc}
                            alt="Finished poster preview"
                            className="max-h-80 w-auto rounded border border-border bg-black"
                        />
                        {showGuides && previewB64 && <GuideOverlay />}
                    </div>
                    {previewB64 && <GuidesToggle show={showGuides} onChange={setShowGuides} />}
                </div>
            )}
            {file && (
                <LogoSelector
                    label="Add a logo (optional)"
                    logos={logos}
                    loading={loadingArt}
                    selected={logo}
                    onSelect={onPickLogo}
                    customLogo={customLogo}
                    onCustomChange={onCustomLogo}
                    scale={logoScale}
                    onScale={onLogoScale}
                    yOffset={logoYOffset}
                    onYOffset={onLogoYOffset}
                    whiten={effectiveWhiten}
                    onWhiten={v => {
                        setWhitenLogo(v);
                        setPreviewB64(null);
                    }}
                    emptyText="No TMDB/fanart logos — upload a custom one, or leave unset to keep the poster as-is."
                />
            )}
            <label className="flex items-center gap-2 text-sm text-primary font-medium">
                <input
                    type="checkbox"
                    checked={addBorder}
                    onChange={e => onToggleBorder(e.target.checked)}
                />
                Add CL2K white border
            </label>
            <p className="text-xs text-tertiary">
                The DAPS default 26px white frame (per the CL2K PSD). Uncheck only if this poster
                already has the required border.
            </p>
            <SaveTargets targets={saveTargets} />
            <div className="flex gap-2">
                <LoadingButton
                    onClick={runPreview}
                    loading={previewing}
                    disabled={!file}
                    variant="secondary"
                    icon="visibility"
                >
                    Preview
                </LoadingButton>
                <LoadingButton
                    onClick={submit}
                    loading={busy}
                    disabled={!file || saveTargets.noTarget}
                    icon="save"
                >
                    Save poster
                </LoadingButton>
            </div>
        </section>
    );
};

// ─── Synced-poster picker (browse the GDrive sync cache) ────────────────────

// Browse the poster_cache (synced jpg/png/webp — the sync never pulls PSDs) and
// pick a finished poster to re-text. Thumbnails are display-only; the parent
// re-fetches the full-resolution original on pick so the edit stays lossless.
const SyncImportPicker = ({ defaultQuery, importing, onPick, toast }) => {
    const [owner, setOwner] = useState('');
    const [query, setQuery] = useState(defaultQuery || '');
    const [owners, setOwners] = useState([]);
    const [items, setItems] = useState(null);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true); // fetches once on mount

    // The browse itself — sets results only after the await, so it's safe to run
    // straight from the mount effect (no synchronous setState in the effect body).
    const fetchPosters = useCallback(async () => {
        try {
            const resp = await postersAPI.browsePosters({
                query: query.trim() || undefined,
                owner: owner || undefined,
                image_type: 'poster',
                limit: 60,
            });
            const data = resp?.data || {};
            setItems(data.items || []);
            setTotal(data.total || 0);
            if (data.owners) setOwners(data.owners);
        } catch (err) {
            setItems([]);
            toast.error(err.message || 'Browse failed');
        }
    }, [query, owner, toast]);

    const run = useCallback(async () => {
        setLoading(true);
        try {
            await fetchPosters();
        } finally {
            setLoading(false);
        }
    }, [fetchPosters]);

    // Auto-search once for the current title so the right poster surfaces on open.
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                await fetchPosters();
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
        // Initial fetch only — fetchPosters captures the opening title/owner.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
                <select
                    value={owner}
                    onChange={e => setOwner(e.target.value)}
                    className="bg-surface border border-border rounded px-2 py-1 text-sm text-primary"
                >
                    <option value="">All owners</option>
                    {owners.map(o => (
                        <option key={o} value={o}>
                            {o}
                        </option>
                    ))}
                </select>
                <form
                    onSubmit={e => {
                        e.preventDefault();
                        run();
                    }}
                    className="flex items-center gap-2 flex-1 min-w-[12rem]"
                >
                    <input
                        type="text"
                        value={query}
                        onChange={e => setQuery(e.target.value)}
                        placeholder="Title substring (blank = list all)"
                        className="flex-1 bg-surface border border-border rounded px-2 py-1 text-sm text-primary"
                    />
                    <LoadingButton type="submit" loading={loading} icon="search" size="small">
                        Search
                    </LoadingButton>
                </form>
            </div>

            {loading && <div className="text-xs text-tertiary">Searching…</div>}
            {items && items.length === 0 && !loading && (
                <div className="text-xs text-tertiary">
                    No matching synced posters — try a different title or owner. Only images already
                    pulled by Sync GDrive appear here.
                </div>
            )}
            {items && items.length > 0 && (
                <>
                    <div className="text-xs text-tertiary">
                        {total} match{total === 1 ? '' : 'es'}
                        {total > items.length ? ` — showing first ${items.length}, refine` : ''}
                    </div>
                    <div
                        className="grid gap-2 max-h-80 overflow-auto"
                        style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(96px, 1fr))' }}
                    >
                        {items.map(p => (
                            <button
                                key={p.id || `${p.folder}/${p.file}`}
                                type="button"
                                disabled={importing}
                                onClick={() => onPick(p)}
                                title={p.file}
                                className="relative bg-surface-alt overflow-hidden rounded border border-border hover:border-primary disabled:opacity-50 p-0"
                                style={{ aspectRatio: '2 / 3' }}
                            >
                                <img
                                    src={
                                        p.id
                                            ? postersAPI.getThumbnailUrl(p.id, 200)
                                            : postersAPI.getPreviewUrl(p.folder, p.file)
                                    }
                                    alt={p.file}
                                    loading="lazy"
                                    className="w-full h-full object-cover"
                                />
                                {p.style && (
                                    <span
                                        className="absolute top-1.5 left-1.5 z-10 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-black/65 text-white backdrop-blur-sm pointer-events-none"
                                        title={`Style: ${p.style}`}
                                    >
                                        {p.style}
                                    </span>
                                )}
                            </button>
                        ))}
                    </div>
                </>
            )}
            {importing && (
                <div className="text-xs text-tertiary">Importing full-resolution poster…</div>
            )}
        </div>
    );
};

// ─── Edit poster (AI-erase old text + redraw label in CL2K font) ────────────

const EditPosterPanel = ({
    item,
    effectiveKind,
    config,
    logos,
    loadingArt,
    saveTargets,
    toast,
}) => {
    // The uploaded poster (data URL) is the immutable SOURCE. `workingB64` is the
    // base we draw labels onto — it starts as the upload and becomes the AI-erased
    // image after "Send to AI". That's the whole cost trick: the paid OpenAI erase
    // runs ONCE; every label tweak after is a free, deterministic server overlay
    // (apply_ai=false) onto the working copy — no more AI calls.
    const [imageDataUrl, setImageDataUrl] = useState(null);
    const [workingB64, setWorkingB64] = useState(null); // raw base64 (no data prefix)
    const [aiErased, setAiErased] = useState(false);
    const [maskB64, setMaskB64] = useState(null);
    const [brushSize, setBrushSize] = useState(18);
    // Prompt defaults to the module-settings ai_prompt, editable per-edit.
    const [prompt, setPrompt] = useState(() => config?.ai_prompt || '');
    const [label, setLabel] = useState('');
    const [textY, setTextY] = useState(0.96);
    const [seasonNum, setSeasonNum] = useState('');
    const [labeledB64, setLabeledB64] = useState(null); // working copy + label drawn
    const [aiBusy, setAiBusy] = useState(false);
    const [labelBusy, setLabelBusy] = useState(false);
    const [saving, setSaving] = useState(false);
    // Live label positioning: a CSS text overlay tracks the slider instantly while
    // dragging, then snaps to the accurate server render on release. `imgW` scales
    // the overlay font to the rendered poster so it closely matches the CL2K render.
    const [dragging, setDragging] = useState(false);
    const [imgW, setImgW] = useState(0);
    const workImgRef = useRef(null);
    // Add the default 26px white CL2K border on save (DAPS rule); uncheck for a
    // poster that already has the required border.
    const [addBorder, setAddBorder] = useState(true);

    // Output mode. 'retext' = the original flow (label/border, saved as-is).
    // 'cl2k' = run the FULL CL2K render (framing + logo + gradient + border) on
    // the working copy — this absorbs the old "Cleaned backdrop" tab, since the
    // upload + optional AI erase steps are identical.
    const [outputMode, setOutputMode] = useState('retext'); // 'retext' | 'cl2k'
    const [fitMode, setFitMode] = useState('cover');
    const [crop, setCrop] = useState(null);
    const [vPos, setVPos] = useState(0);
    const [zoom, setZoom] = useState(1);
    const [focusX, setFocusX] = useState(0.5);
    const [focusY, setFocusY] = useState(0.5);
    const [cl2kLogo, setCl2kLogo] = useState(null); // chosen TMDB/fanart logo file_path
    const [customLogo, setCustomLogo] = useState(null); // { b64, name, url }
    const [logoScale, setLogoScale] = useState(1);
    const [logoYOffset, setLogoYOffset] = useState(0);
    // Per-render whiten override; null = the module config (whiten_logo) — the
    // FormData builder skips nulls so the backend falls back to the config.
    const [whitenLogo, setWhitenLogo] = useState(null);
    const effectiveWhiten = whitenLogo === null ? (config?.whiten_logo ?? true) : whitenLogo;
    const [cl2kPreviewB64, setCl2kPreviewB64] = useState(null);
    const [cl2kPreviewing, setCl2kPreviewing] = useState(false);
    const [showGuides, setShowGuides] = useState(true);
    const [generating, setGenerating] = useState(false);

    const provider = config?.ai_provider || 'none';
    const isSeason = String(seasonNum).trim() !== '';

    // Where the source poster comes from: a disk upload or the GDrive sync cache.
    const [sourceMode, setSourceMode] = useState('sync'); // 'sync' | 'upload'
    const [importing, setImporting] = useState(false);

    // Seed the editor from a base64 data URL — shared by the file upload and the
    // synced-poster import so both reset the AI/mask/label state identically.
    const loadSource = useCallback(dataUrl => {
        setImageDataUrl(dataUrl);
        setWorkingB64(String(dataUrl).split(',').pop());
        setAiErased(false);
        setMaskB64(null);
        setLabeledB64(null);
        setCl2kPreviewB64(null);
    }, []);

    const onFile = useCallback(
        e => {
            const f = e.target.files?.[0];
            if (!f) return;
            const reader = new FileReader();
            reader.onload = () => loadSource(reader.result);
            reader.readAsDataURL(f);
        },
        [loadSource]
    );

    // Pull a synced poster at FULL resolution — the raw cached file, never the
    // thumbnail — so the edit starts from a pristine image (no recompression).
    const importFromSync = useCallback(
        async poster => {
            setImporting(true);
            try {
                const resp = await fetch(postersAPI.getPreviewUrl(poster.folder, poster.file));
                if (!resp.ok) throw new Error(`Import failed (${resp.status})`);
                const blob = await resp.blob();
                const dataUrl = await new Promise((resolve, reject) => {
                    const r = new FileReader();
                    r.onload = () => resolve(r.result);
                    r.onerror = () => reject(new Error('Could not read image'));
                    r.readAsDataURL(blob);
                });
                loadSource(dataUrl);
            } catch (err) {
                toast.error(err.message || 'Import failed');
            } finally {
                setImporting(false);
            }
        },
        [loadSource, toast]
    );

    // Id/kind fields shared by every /retext call (drive the save filename; inert
    // on previews).
    const idFields = useMemo(
        () => ({
            kind: isSeason ? 'season' : effectiveKind,
            season_number: isSeason ? Number(seasonNum) : null,
            title: item.title,
            tmdb_id: item.tmdb_id,
            year: item.year,
            tvdb_id: item.tvdb_id,
            imdb_id: item.imdb_id,
        }),
        [isSeason, seasonNum, effectiveKind, item]
    );

    // Send to AI — the ONLY paid step. Erase the masked region of the ORIGINAL
    // upload and keep the result as the working copy. No label drawn here.
    const runErase = useCallback(async () => {
        if (!imageDataUrl || !maskB64) return;
        setAiBusy(true);
        try {
            const resp = await cl2kMakerAPI.retext({
                image_b64: imageDataUrl,
                mask_b64: maskB64,
                apply_ai: true,
                prompt,
                label_text: '',
                border: false, // keep the working copy clean; border is applied later
                preview: true,
                // Keep the original dimensions: the CL2K output mode frames the
                // working copy itself, and the re-text save normalizes anyway.
                keep_size: true,
                ...idFields,
            });
            const erased = resp?.data?.preview_b64;
            if (erased) {
                setWorkingB64(erased);
                setAiErased(true);
                setLabeledB64(null);
                setCl2kPreviewB64(null);
                toast.success(
                    'Old text erased — position the label, then save (no more AI calls).'
                );
            } else {
                toast.error('AI returned no image');
            }
        } catch (err) {
            toast.error(err.message || 'AI erase failed');
        } finally {
            setAiBusy(false);
        }
    }, [imageDataUrl, maskB64, prompt, idFields, toast]);

    // Free, deterministic label overlay onto the working copy (apply_ai=false), so
    // the label can be positioned without spending AI credits. Debounced auto-render
    // whenever the label text / position / working copy changes.
    useEffect(() => {
        // Nothing to bake (no label and no border) — the display falls back to the
        // bare working copy (workingSrc ignores a stale render in that case).
        if (!workingB64 || (!label.trim() && !addBorder)) return undefined;
        let cancelled = false;
        const timer = setTimeout(async () => {
            setLabelBusy(true);
            try {
                const resp = await cl2kMakerAPI.retext({
                    image_b64: workingB64,
                    mask_b64: null,
                    apply_ai: false,
                    label_text: label,
                    text_y: textY,
                    border: addBorder,
                    preview: true,
                    ...idFields,
                });
                if (!cancelled) setLabeledB64(resp?.data?.preview_b64 || null);
            } catch (err) {
                if (!cancelled) toast.error(err.message || 'Preview failed');
            } finally {
                if (!cancelled) setLabelBusy(false);
            }
        }, 500);
        return () => {
            cancelled = true;
            clearTimeout(timer);
        };
    }, [workingB64, label, textY, addBorder, idFields, toast]);

    // Re-measure the rendered poster width on resize so the live overlay font scales
    // with it (initial measure happens on the image's onLoad).
    useEffect(() => {
        const measure = () => {
            if (workImgRef.current) setImgW(workImgRef.current.clientWidth);
        };
        window.addEventListener('resize', measure);
        return () => window.removeEventListener('resize', measure);
    }, []);

    // Clear the drag state on any pointer release (even outside the slider), so the
    // view reliably snaps back to the accurate server render.
    useEffect(() => {
        if (!dragging) return undefined;
        const stop = () => setDragging(false);
        window.addEventListener('mouseup', stop);
        window.addEventListener('touchend', stop);
        return () => {
            window.removeEventListener('mouseup', stop);
            window.removeEventListener('touchend', stop);
        };
    }, [dragging]);

    // Save the working copy + label. apply_ai=false → NO second OpenAI call.
    const runSave = useCallback(async () => {
        if (!workingB64) return;
        setSaving(true);
        try {
            const resp = await cl2kMakerAPI.retext({
                image_b64: workingB64,
                mask_b64: null,
                apply_ai: false,
                label_text: label,
                text_y: textY,
                border: addBorder,
                preview: false,
                ...idFields,
                ...saveTargets.fields,
            });
            savedToast(toast, resp?.data);
        } catch (err) {
            toast.error(err.message || 'Save failed');
        } finally {
            setSaving(false);
        }
    }, [workingB64, label, textY, addBorder, idFields, saveTargets.fields, toast]);

    // Download the working copy as shown (label/border baked when rendered) so the
    // cleaned poster can be taken elsewhere — e.g. the Finished-poster tab to add a
    // clear logo. Pure client-side: the bytes are already here as base64.
    const downloadWorking = useCallback(() => {
        const baked = (label.trim() || addBorder) && labeledB64;
        const b64 = baked ? labeledB64 : workingB64;
        if (!b64) return;
        const a = document.createElement('a');
        a.href = `data:image/jpeg;base64,${b64}`;
        a.download = `${item.title || 'poster'} (cleaned).jpg`;
        a.click();
    }, [label, addBorder, labeledB64, workingB64, item.title]);

    // ── Full-CL2K output mode ──────────────────────────────────────────────
    const onCustomLogo = useCallback(c => {
        setCustomLogo(c);
        setCl2kPreviewB64(null);
        if (c) setCl2kLogo(null);
    }, []);

    // The working copy (original upload or AI-erased) as a multipart upload for
    // the full-render endpoint — the bytes are already here as base64.
    const workingFile = useCallback(() => {
        if (!workingB64) return null;
        const bin = atob(workingB64);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
        return new File([bytes], 'working.jpg', { type: 'image/jpeg' });
    }, [workingB64]);

    const cl2kMeta = useMemo(
        () => ({
            ...idFields,
            logo_path: customLogo ? null : cl2kLogo,
            logo_b64: customLogo?.b64 || null,
            logo_scale: logoScale,
            logo_y_offset: logoYOffset,
            whiten: whitenLogo,
            fit_mode: fitMode,
            focus_x: focusX,
            focus_y: focusY,
            crop_x: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.x : null,
            crop_y: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.y : null,
            crop_w: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.w : null,
            crop_h: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.h : null,
            v_pos: vPos,
            zoom: fitMode === 'fit' || fitMode === 'extend' ? zoom : 1,
        }),
        [
            idFields,
            cl2kLogo,
            customLogo,
            logoScale,
            logoYOffset,
            whitenLogo,
            fitMode,
            crop,
            vPos,
            zoom,
            focusX,
            focusY,
        ]
    );

    const runCl2kPreview = useCallback(async () => {
        const f = workingFile();
        if (!f) return;
        setCl2kPreviewing(true);
        try {
            const resp = await cl2kMakerAPI.uploadGenerate(f, { ...cl2kMeta, preview: true });
            setCl2kPreviewB64(resp?.data?.preview_b64 || null);
        } catch (err) {
            toast.error(err.message || 'Preview failed');
        } finally {
            setCl2kPreviewing(false);
        }
    }, [workingFile, cl2kMeta, toast]);

    const runCl2kGenerate = useCallback(async () => {
        const f = workingFile();
        if (!f) return;
        setGenerating(true);
        try {
            const resp = await cl2kMakerAPI.uploadGenerate(f, {
                ...cl2kMeta,
                ...saveTargets.fields,
            });
            savedToast(toast, resp?.data, 'Generated');
        } catch (err) {
            toast.error(err.message || 'Generate failed');
        } finally {
            setGenerating(false);
        }
    }, [workingFile, cl2kMeta, saveTargets.fields, toast]);

    // What the working-copy pane shows.
    // bareSrc = working copy with NO baked label; labeledSrc = the accurate server
    // render (label baked in). While dragging the position, or before the server
    // render catches up, show bareSrc + a live CSS label; otherwise show the
    // pixel-accurate render.
    const bareSrc = aiErased ? `data:image/jpeg;base64,${workingB64}` : imageDataUrl;
    const labeledSrc = labeledB64 ? `data:image/jpeg;base64,${labeledB64}` : null;
    // Something to bake server-side (a label and/or the border)?
    const hasRender = !!label.trim() || addBorder;
    const liveLabel = !!label.trim() && (dragging || labelBusy || !labeledSrc);
    const workingSrc = liveLabel ? bareSrc : hasRender && labeledSrc ? labeledSrc : bareSrc;
    // CL2K label metrics scaled to the rendered poster: 32px per 1000px canvas width,
    // tracking 0.8em — an approximation of overlay_label, replaced by the real render.
    const overlayPx = imgW ? (32 * imgW) / 1000 : 0;

    return (
        <section className="mt-4 flex flex-col gap-4">
            {/* Full-width source bar — keeps the two posters below it top-aligned. */}
            <div className="bg-surface border border-border rounded-lg p-3 flex flex-col gap-2">
                <h3 className="text-sm font-medium text-primary">Edit poster</h3>
                <p className="text-xs text-tertiary">
                    Import a poster or backdrop from your GDrive sync (or upload one). Optionally
                    brush over old text and <span className="text-secondary">Send to AI</span> once
                    to erase it — that&apos;s the only step that uses AI credits. Then either
                    re-text it (label/border, saved as-is) or run the full CL2K render (framing,
                    logo, gradient, border) on the result.
                </p>
                <div className="flex gap-2">
                    <Button
                        variant={sourceMode === 'sync' ? 'primary' : 'secondary'}
                        size="small"
                        icon="cloud_sync"
                        onClick={() => setSourceMode('sync')}
                    >
                        Import from sync
                    </Button>
                    <Button
                        variant={sourceMode === 'upload' ? 'primary' : 'secondary'}
                        size="small"
                        icon="upload"
                        onClick={() => setSourceMode('upload')}
                    >
                        Upload file
                    </Button>
                </div>
                {sourceMode === 'upload' ? (
                    <input type="file" accept="image/*" onChange={onFile} />
                ) : (
                    <SyncImportPicker
                        defaultQuery={item.title}
                        importing={importing}
                        onPick={importFromSync}
                        toast={toast}
                    />
                )}
            </div>

            {imageDataUrl && (
                <div className="bg-surface border border-border rounded-lg p-3 flex flex-col gap-2">
                    <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-primary">Output</span>
                        <Button
                            variant={outputMode === 'retext' ? 'primary' : 'secondary'}
                            size="small"
                            icon="text_fields"
                            onClick={() => setOutputMode('retext')}
                        >
                            Re-text &amp; save as-is
                        </Button>
                        <Button
                            variant={outputMode === 'cl2k' ? 'primary' : 'secondary'}
                            size="small"
                            icon="auto_awesome"
                            onClick={() => setOutputMode('cl2k')}
                        >
                            Full CL2K render
                        </Button>
                    </div>
                    <p className="text-xs text-tertiary">
                        {outputMode === 'retext'
                            ? 'Draw a label and file the poster as-is — no CL2K logo or gradient added.'
                            : 'Frame the working copy, pick a clear logo, and render the full CL2K treatment (gradient + logo + border).'}
                    </p>
                </div>
            )}

            {imageDataUrl && (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    {/* LEFT — source: brush the old text, send to AI once */}
                    <div className="bg-surface border border-border rounded-lg p-3 flex flex-col gap-3">
                        <div className="flex items-center justify-between">
                            <h3 className="text-sm font-medium text-primary">
                                Source — brush the old text
                            </h3>
                            {aiErased && (
                                <span className="inline-flex items-center gap-1 text-xs text-success">
                                    <span className="material-symbols-outlined text-sm">
                                        check_circle
                                    </span>
                                    erased
                                </span>
                            )}
                        </div>
                        <BrushMask
                            imageUrl={imageDataUrl}
                            brushSize={brushSize}
                            onMaskChange={setMaskB64}
                        />
                        <label className="flex items-center gap-2 text-sm text-secondary">
                            <span className="w-20">Brush</span>
                            <input
                                type="range"
                                min="4"
                                max="60"
                                value={brushSize}
                                onChange={e => setBrushSize(Number(e.target.value))}
                                className="flex-1"
                            />
                            <span className="w-10 text-right">{brushSize}px</span>
                        </label>
                        <label className="flex flex-col gap-1 text-sm text-secondary">
                            <span>AI prompt (defaults to module settings)</span>
                            <textarea
                                value={prompt}
                                onChange={e => setPrompt(e.target.value)}
                                rows={2}
                                className="bg-surface border border-border rounded px-2 py-1 text-sm text-primary"
                            />
                        </label>
                        {provider === 'none' && (
                            <div className="text-xs text-warning">
                                AI provider is “none” — enable OpenAI in{' '}
                                <Link
                                    to="/settings/modules"
                                    className="text-primary underline hover:no-underline"
                                >
                                    Module Settings
                                </Link>{' '}
                                to erase text.
                            </div>
                        )}
                        <LoadingButton
                            onClick={runErase}
                            loading={aiBusy}
                            disabled={!maskB64 || provider === 'none'}
                            icon="auto_fix_high"
                        >
                            {aiErased
                                ? 'Re-send to AI (erase again)'
                                : 'Send to AI — erase masked text'}
                        </LoadingButton>
                        <p className="text-xs text-tertiary">
                            Provider: <span className="text-secondary">{provider}</span>. This is
                            the only step that uses AI credits — brush the old text, then send once.
                        </p>
                    </div>

                    {/* RIGHT — output: re-text (label/save-as-is) or full CL2K render */}
                    {outputMode === 'cl2k' ? (
                        <div className="flex flex-col gap-3 self-start sticky top-4 max-h-screen overflow-y-auto">
                            <CropFramer
                                imageUrl={bareSrc}
                                fitMode={fitMode}
                                setFitMode={setFitMode}
                                crop={crop}
                                setCrop={setCrop}
                                vPos={vPos}
                                setVPos={setVPos}
                                zoom={zoom}
                                setZoom={setZoom}
                                focusX={focusX}
                                focusY={focusY}
                                onChange={(fx, fy) => {
                                    setFocusX(fx);
                                    setFocusY(fy);
                                }}
                            />
                            <LogoSelector
                                label="Logo (TMDB / fanart / custom)"
                                logos={logos}
                                loading={loadingArt}
                                selected={cl2kLogo}
                                onSelect={p => {
                                    setCl2kLogo(p);
                                    setCl2kPreviewB64(null);
                                }}
                                customLogo={customLogo}
                                onCustomChange={onCustomLogo}
                                scale={logoScale}
                                onScale={s => {
                                    setLogoScale(s);
                                    setCl2kPreviewB64(null);
                                }}
                                whiten={effectiveWhiten}
                                onWhiten={v => {
                                    setWhitenLogo(v);
                                    setCl2kPreviewB64(null);
                                }}
                                yOffset={logoYOffset}
                                onYOffset={y => {
                                    setLogoYOffset(y);
                                    setCl2kPreviewB64(null);
                                }}
                                emptyText="No TMDB/fanart logos — upload a custom one, or leave unset for the text-wordmark fallback."
                            />
                            <div className="bg-surface border border-border rounded-lg p-3">
                                <div className="flex items-center justify-between mb-2">
                                    <h3 className="text-sm font-medium text-primary">Preview</h3>
                                    <div className="flex items-center gap-3">
                                        <GuidesToggle show={showGuides} onChange={setShowGuides} />
                                        <LoadingButton
                                            onClick={runCl2kPreview}
                                            loading={cl2kPreviewing}
                                            disabled={!workingB64}
                                            icon="visibility"
                                            size="small"
                                        >
                                            Render preview
                                        </LoadingButton>
                                    </div>
                                </div>
                                <div className="relative aspect-[2/3] bg-black rounded overflow-hidden flex items-center justify-center">
                                    {cl2kPreviewB64 ? (
                                        <>
                                            <img
                                                src={`data:image/jpeg;base64,${cl2kPreviewB64}`}
                                                alt="CL2K preview"
                                                className="w-full h-full object-contain"
                                            />
                                            {showGuides && <GuideOverlay />}
                                        </>
                                    ) : (
                                        <span className="text-xs text-tertiary px-4 text-center">
                                            Click “Render preview”.
                                        </span>
                                    )}
                                </div>
                            </div>
                            <div className="bg-surface border border-border rounded-lg p-3 flex flex-col gap-2">
                                <SaveTargets targets={saveTargets} />
                                <LoadingButton
                                    onClick={runCl2kGenerate}
                                    loading={generating}
                                    disabled={!workingB64 || saveTargets.noTarget}
                                    icon="save"
                                >
                                    Generate &amp; save
                                </LoadingButton>
                                <Button
                                    onClick={downloadWorking}
                                    disabled={!workingB64}
                                    variant="secondary"
                                    icon="download"
                                >
                                    Download working copy
                                </Button>
                            </div>
                        </div>
                    ) : (
                        <div className="bg-surface border border-border rounded-lg p-3 flex flex-col gap-3 self-start sticky top-4 max-h-screen overflow-y-auto">
                            <div className="flex items-center justify-between">
                                <h3 className="text-sm font-medium text-primary">Working copy</h3>
                                {labelBusy && (
                                    <span className="text-xs text-tertiary">updating…</span>
                                )}
                            </div>
                            <div className="aspect-[2/3] bg-black rounded overflow-hidden flex items-center justify-center relative">
                                {workingSrc ? (
                                    <>
                                        <img
                                            ref={workImgRef}
                                            src={workingSrc}
                                            alt="Working copy"
                                            onLoad={e => setImgW(e.target.clientWidth)}
                                            className="w-full h-full object-contain"
                                        />
                                        {liveLabel && overlayPx > 0 && (
                                            <div
                                                style={{
                                                    position: 'absolute',
                                                    left: 0,
                                                    right: 0,
                                                    top: `${textY * 100}%`,
                                                    transform: 'translateY(-50%)',
                                                    textAlign: 'center',
                                                    color: '#fff',
                                                    textTransform: 'uppercase',
                                                    fontFamily: 'Arial, Helvetica, sans-serif',
                                                    fontWeight: 400,
                                                    fontSize: `${overlayPx}px`,
                                                    letterSpacing: `${overlayPx * 0.8}px`,
                                                    lineHeight: 1,
                                                    whiteSpace: 'nowrap',
                                                    pointerEvents: 'none',
                                                }}
                                            >
                                                {label}
                                            </div>
                                        )}
                                    </>
                                ) : (
                                    <span className="text-xs text-tertiary px-4 text-center">
                                        Import a synced poster or upload one to start.
                                    </span>
                                )}
                            </div>
                            <label className="flex flex-col gap-1 text-sm text-secondary">
                                <span>Label text (drawn on the poster)</span>
                                <input
                                    type="text"
                                    value={label}
                                    onChange={e => setLabel(e.target.value)}
                                    placeholder="e.g. SEASON 2026"
                                    className="bg-surface border border-border rounded px-2 py-1 text-sm text-primary"
                                />
                            </label>
                            <label className="flex items-center gap-2 text-sm text-secondary">
                                <span className="w-24">Position</span>
                                <input
                                    type="range"
                                    min="0"
                                    max="100"
                                    value={Math.round(textY * 100)}
                                    onChange={e => setTextY(Number(e.target.value) / 100)}
                                    onMouseDown={() => setDragging(true)}
                                    onTouchStart={() => setDragging(true)}
                                    className="flex-1"
                                />
                                <span className="w-10 text-right">{Math.round(textY * 100)}%</span>
                            </label>
                            <p className="text-xs text-tertiary">
                                <span className="text-secondary">
                                    96% is the locked CL2K default
                                </span>{' '}
                                — the season/specials band from the CL2K PSD (y=1440 on the 1500px
                                canvas). Drag for a live preview; it snaps to the exact CL2K render
                                on release.{' '}
                                {Math.round(textY * 100) !== 96 && (
                                    <button
                                        type="button"
                                        onClick={() => setTextY(0.96)}
                                        className="text-primary underline hover:no-underline"
                                    >
                                        Reset to CL2K default
                                    </button>
                                )}
                            </p>
                            <label className="flex flex-col gap-1 text-sm text-secondary">
                                <span>Season number (filename + Plex match — not drawn)</span>
                                <input
                                    type="number"
                                    value={seasonNum}
                                    onChange={e => setSeasonNum(e.target.value)}
                                    placeholder="blank = base poster; e.g. 2026"
                                    className="bg-surface border border-border rounded px-2 py-1 text-sm text-primary"
                                />
                            </label>
                            <p className="text-xs text-tertiary">
                                {String(seasonNum).trim() === '' ? (
                                    <>Blank = base show poster (no season suffix). </>
                                ) : (
                                    <>
                                        Sets the filename suffix{' '}
                                        <code className="text-secondary">
                                            {seasonSuffixPreview(seasonNum)}
                                        </code>{' '}
                                        so Poster Renamerr applies it to that season.{' '}
                                    </>
                                )}
                                Use <code className="text-secondary">0</code> for Specials. For
                                year-based shows (F1) use the year (e.g. 2026). Metadata only — it
                                isn’t printed on the poster.
                            </p>
                            <label className="flex items-center gap-2 text-sm text-primary font-medium">
                                <input
                                    type="checkbox"
                                    checked={addBorder}
                                    onChange={e => setAddBorder(e.target.checked)}
                                />
                                Add CL2K white border
                            </label>
                            <p className="text-xs text-tertiary">
                                The DAPS default 26px white frame (per the CL2K PSD). Uncheck only
                                if the source poster already has the required border.
                            </p>
                            <SaveTargets targets={saveTargets} />
                            <LoadingButton
                                onClick={runSave}
                                loading={saving}
                                disabled={!workingB64 || saveTargets.noTarget}
                                icon="save"
                            >
                                Save edited poster
                            </LoadingButton>
                            <p className="text-xs text-tertiary">
                                Saving draws the label and files it (1000×1500, DAPS-named) — no
                                extra AI call.
                            </p>
                            <Button
                                onClick={downloadWorking}
                                disabled={!workingB64}
                                variant="secondary"
                                icon="download"
                            >
                                Download working copy
                            </Button>
                            <p className="text-xs text-tertiary">
                                Downloads what’s shown (label/border included if set) — e.g. to add
                                a clear logo via the Finished poster tab. Uncheck the border first
                                if you’ll add it there instead.
                            </p>
                        </div>
                    )}
                </div>
            )}
        </section>
    );
};

// ─── History ────────────────────────────────────────────────────────────────

const HistorySection = ({ toast }) => {
    const [items, setItems] = useState(null);
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const resp = await cl2kMakerAPI.generated(50);
            setItems(resp?.data?.items || []);
        } catch (err) {
            toast.error(err.message || 'Failed to load history');
        } finally {
            setLoading(false);
        }
    }, [toast]);

    const toggle = useCallback(() => {
        setOpen(o => {
            const next = !o;
            if (next && items === null) load();
            return next;
        });
    }, [items, load]);

    return (
        <section className="mt-8 bg-surface border border-border rounded-lg">
            <button
                type="button"
                onClick={toggle}
                className="w-full flex items-center justify-between p-3 hover:bg-surface-alt"
            >
                <span className="text-sm font-medium text-primary">Recently generated</span>
                <span className="material-symbols-outlined text-tertiary">
                    {open ? 'expand_less' : 'expand_more'}
                </span>
            </button>
            {open && (
                <div className="p-3 border-t border-border-subtle">
                    {loading ? (
                        <Spinner size="small" text="Loading…" />
                    ) : !items || items.length === 0 ? (
                        <div className="text-xs text-tertiary">Nothing generated yet.</div>
                    ) : (
                        <ul className="divide-y divide-border text-sm">
                            {items.map((it, idx) => (
                                <li
                                    key={`${it.file || idx}`}
                                    className="py-2 flex items-center justify-between gap-3"
                                >
                                    <span className="text-primary truncate">
                                        {it.title || it.file}
                                        {it.season_number != null && (
                                            <span className="text-tertiary">
                                                {' '}
                                                · S{it.season_number}
                                            </span>
                                        )}
                                    </span>
                                    <span className="text-xs text-tertiary shrink-0">
                                        {it.kind} · logo: {it.logo_source || '—'}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            )}
        </section>
    );
};

// ─── helpers ────────────────────────────────────────────────────────────────

const TMDB_CDN = 'https://image.tmdb.org/t/p/original';
const urlForPath = path => (path?.startsWith('http') ? path : `${TMDB_CDN}${path}`);

const slugify = s =>
    (s || '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/(^-|-$)/g, '');

const parseSeasonList = s =>
    (s || '')
        .split(',')
        .map(x => parseInt(x.trim(), 10))
        .filter(n => Number.isInteger(n) && n >= 0);

// Preview the filename suffix the backend (build_poster_filename) will write:
// season 0 → "- Specials", others → "- Season NN" (zero-padded to 2 digits,
// year-based F1 numbers pass through, e.g. "- Season 2026").
const seasonSuffixPreview = season => {
    const n = Number(String(season).trim());
    if (!Number.isFinite(n)) return '';
    if (n === 0) return '- Specials';
    return `- Season ${String(n).padStart(2, '0')}`;
};

const downloadBlob = (blob, filename) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
};

// Toast for a save/generate that also surfaces a non-fatal Drive-upload failure
// (the poster still saved locally) so the user isn't left guessing why nothing
// reached Drive. Backend returns data.upload_error on the save response.
const savedToast = (toast, data, verb = 'Saved') => {
    const file = data?.file || 'poster';
    if (data?.upload_error) {
        toast.error(`${verb} ${file} locally, but Drive upload failed: ${data.upload_error}`);
        return;
    }
    const local = data?.saved_local;
    const uploaded = data?.uploaded;
    if (local && uploaded) {
        toast.success(`${verb}: ${file} (local + Drive)`);
    } else if (uploaded && !local) {
        toast.success(`${verb} to Drive: ${file}`);
    } else {
        toast.success(`${verb}: ${file}`);
    }
};

export default Cl2kMakerPage;
