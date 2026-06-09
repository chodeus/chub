import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { cl2kMakerAPI } from '../../utils/api/cl2k_maker.js';
import { configAPI } from '../../utils/api/config.js';
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

const SOURCE_TABS = [
    { key: 'tmdb', label: 'TMDB', icon: 'movie' },
    { key: 'fanart', label: 'fanart.tv', icon: 'palette' },
    { key: 'upload-backdrop', label: 'Cleaned backdrop', icon: 'auto_fix_high' },
    { key: 'upload-poster', label: 'Finished poster', icon: 'image' },
    { key: 'gdrive-psd', label: 'Drive .psd', icon: 'cloud' },
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
            // Fill in whichever of tvdb/imdb the paste didn't already supply.
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

    const [tab, setTab] = useState(saved.tab ?? 'tmdb');
    const [editIds, setEditIds] = useState(false);

    // Save destinations (output dir / Drive) — shared by every save flow below.
    const saveTargets = useSaveTargets(uploadStatus);

    // Art (shared across the TMDB / fanart tabs)
    const [tmdbArt, setTmdbArt] = useState(null);
    const [fanartArt, setFanartArt] = useState(null);
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

    // Crop framing: focal point (0..1) for the backdrop cover-crop. 0.5 = centre.
    const [focusX, setFocusX] = useState(saved.focusX ?? 0.5);
    const [focusY, setFocusY] = useState(saved.focusY ?? 0.5);

    // Season variant (shows only)
    const [seasonNumber, setSeasonNumber] = useState(saved.seasonNumber ?? '');
    const [bulkSeasons, setBulkSeasons] = useState(saved.bulkSeasons ?? '');

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
            focusX,
            focusY,
            seasonNumber,
            bulkSeasons,
            removeText,
        });
    }, [tab, backdrop, logo, focusX, focusY, seasonNumber, bulkSeasons, removeText]);

    // Preview
    const [previewUrl, setPreviewUrl] = useState(null);
    const [previewing, setPreviewing] = useState(false);
    const [busy, setBusy] = useState(false);

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
            remove_text: removeText,
            mask_b64: removeText ? maskB64 : null,
            focus_x: focusX,
            focus_y: focusY,
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
            removeText,
            maskB64,
            focusX,
            focusY,
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

    const runPreview = useCallback(async () => {
        setPreviewing(true);
        try {
            const blob = await cl2kMakerAPI.preview(baseRequest);
            setPreview(blob);
        } catch (err) {
            toast.error(err.message || 'Preview failed');
        } finally {
            setPreviewing(false);
        }
    }, [baseRequest, setPreview, toast]);

    const runGenerate = useCallback(async () => {
        setBusy(true);
        try {
            const resp = await cl2kMakerAPI.generate({ ...baseRequest, force: false });
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
                force: false,
            });
            const results = resp?.data?.results || [];
            const gen = results.filter(r => r.status === 'generated').length;
            toast.success(`Seasons: ${gen}/${results.length} generated`);
        } catch (err) {
            toast.error(err.message || 'Season generation failed');
        } finally {
            setBusy(false);
        }
    }, [bulkSeasons, item, toast]);

    const activeArt = tab === 'fanart' ? fanartArt : tmdbArt;
    const isRenderTab = tab === 'tmdb' || tab === 'fanart';

    // TMDB + fanart logos merged, for the uploaded-canvas tabs (which have no
    // source sub-tab of their own). De-duplicated by file_path.
    const allLogos = useMemo(() => {
        const merged = [...(tmdbArt?.logos || []), ...(fanartArt?.logos || [])];
        const seen = new Set();
        return merged.filter(l => {
            if (!l?.file_path || seen.has(l.file_path)) return false;
            seen.add(l.file_path);
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
                    loadingArt={loadingArt}
                    source={tab}
                    backdrop={backdrop}
                    setBackdrop={setBackdrop}
                    logo={logo}
                    setLogo={setLogo}
                    customLogo={customLogo}
                    setCustomLogo={setCustomLogoExclusive}
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

            {tab === 'upload-backdrop' && (
                <UploadBackdropPanel
                    item={item}
                    effectiveKind={effectiveKind}
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
                    saveTargets={saveTargets}
                    toast={toast}
                />
            )}
            {tab === 'gdrive-psd' && (
                <GdrivePsdPanel
                    item={item}
                    effectiveKind={effectiveKind}
                    saveTargets={saveTargets}
                    toast={toast}
                />
            )}
            {tab === 'edit' && (
                <EditPosterPanel
                    item={item}
                    effectiveKind={effectiveKind}
                    config={config}
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
    loadingArt,
    source,
    backdrop,
    setBackdrop,
    logo,
    setLogo,
    customLogo,
    setCustomLogo,
    focusX,
    focusY,
    onFocusChange,
    item,
    config,
    seasonNumber,
    setSeasonNumber,
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
    const backdropUrl = backdrop ? urlForPath(backdrop) : null;

    return (
        <section className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Left: pickers + AI */}
            <div className="flex flex-col gap-4">
                <Picker
                    label={`Backdrop (${source})`}
                    items={backdrops}
                    loading={loadingArt}
                    selected={backdrop}
                    onSelect={setBackdrop}
                    aspect="aspect-video"
                    emptyText="No backdrops from this source."
                />

                {backdropUrl && (
                    <CropFramer
                        imageUrl={backdropUrl}
                        focusX={focusX}
                        focusY={focusY}
                        onChange={onFocusChange}
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

            {/* Right: preview + output */}
            <div className="flex flex-col gap-3">
                <div className="bg-surface border border-border rounded-lg p-3">
                    <div className="flex items-center justify-between mb-2">
                        <h3 className="text-sm font-medium text-primary">Preview</h3>
                        <LoadingButton
                            onClick={onPreview}
                            loading={previewing}
                            disabled={!backdrop}
                            icon="visibility"
                            size="small"
                        >
                            Render preview
                        </LoadingButton>
                    </div>
                    <div className="aspect-[2/3] bg-black rounded overflow-hidden flex items-center justify-center">
                        {previewUrl ? (
                            <img
                                src={previewUrl}
                                alt="CL2K preview"
                                className="w-full h-full object-contain"
                            />
                        ) : (
                            <span className="text-xs text-tertiary px-4 text-center">
                                {backdrop
                                    ? 'Click “Render preview”.'
                                    : 'Select a backdrop to preview.'}
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
                                title="Download the backdrop to clean externally (Firefly/Photoshop), then re-import via the Cleaned backdrop tab"
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
                        back via the <span className="text-secondary">Cleaned backdrop</span> tab.
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
const CropFramer = ({ imageUrl, focusX, focusY, onChange }) => {
    const wrapRef = useRef(null);
    const [dims, setDims] = useState(null);
    const dragging = useRef(false);

    const rect = useMemo(() => {
        if (!dims) return null;
        const target = 2 / 3; // CL2K canvas aspect (w:h)
        let w, h;
        if (dims.w / dims.h > target) {
            h = dims.h;
            w = h * target;
        } else {
            w = dims.w;
            h = w / target;
        }
        const left = Math.max(0, Math.min(focusX * dims.w - w / 2, dims.w - w));
        const top = Math.max(0, Math.min(focusY * dims.h - h / 2, dims.h - h));
        return { left, top, w, h };
    }, [dims, focusX, focusY]);

    const setFromEvent = useCallback(
        e => {
            const el = wrapRef.current;
            if (!el || !dims) return;
            const r = el.getBoundingClientRect();
            const cx = (e.touches?.[0]?.clientX ?? e.clientX) - r.left;
            const cy = (e.touches?.[0]?.clientY ?? e.clientY) - r.top;
            onChange(clamp01(cx / dims.w), clamp01(cy / dims.h));
        },
        [dims, onChange]
    );

    const down = useCallback(
        e => {
            e.preventDefault();
            dragging.current = true;
            setFromEvent(e);
        },
        [setFromEvent]
    );
    const moveEvt = useCallback(
        e => {
            if (dragging.current) setFromEvent(e);
        },
        [setFromEvent]
    );
    const up = useCallback(() => {
        dragging.current = false;
    }, []);

    return (
        <div className="bg-surface border border-border rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-medium text-primary">Crop framing</h3>
                <Button
                    onClick={() => onChange(0.5, 0.5)}
                    variant="secondary"
                    icon="filter_center_focus"
                    size="small"
                >
                    Center
                </Button>
            </div>
            <p className="text-xs text-tertiary mb-2">
                Drag to choose what stays in the 2:3 crop. The dimmed area is cut. Re-render the
                preview to see the result.
            </p>
            <div
                ref={wrapRef}
                className="relative inline-block leading-none select-none overflow-hidden rounded cursor-crosshair"
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
                    onLoad={e => setDims({ w: e.target.clientWidth, h: e.target.clientHeight })}
                    className="block max-w-full"
                    draggable={false}
                />
                {rect && (
                    <div
                        className="absolute border-2 border-primary"
                        style={{
                            left: rect.left,
                            top: rect.top,
                            width: rect.w,
                            height: rect.h,
                            boxShadow: '0 0 0 9999px rgba(0,0,0,0.5)',
                            pointerEvents: 'none',
                        }}
                    />
                )}
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
                                    <span className="material-symbols-outlined text-sm">check</span>
                                </span>
                            )}
                            {it.width ? (
                                <span className="absolute bottom-0 right-0 text-[11px] font-mono text-white bg-black/60 px-1">
                                    {it.width}×{it.height}
                                </span>
                            ) : null}
                        </button>
                    );
                })}
            </div>
        )}
    </div>
);

// ─── Logo selector (TMDB / fanart grid + custom upload) ─────────────────────

// A logo source picker shared by the render + uploaded-canvas flows. Pick a
// TMDB/fanart logo, or upload a custom PNG. A custom logo takes priority and
// hides the grid until removed; the chosen logo is whitened + placed on the CL2K
// guides by the backend (renderer._place_logo), so any source is CL2K-correct.
const LogoSelector = ({
    label = 'Logo',
    logos = [],
    loading = false,
    selected,
    onSelect,
    customLogo,
    onCustomChange,
    emptyText = 'No logos from this source — a text wordmark is used as fallback.',
}) => {
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
                <label className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs border border-border text-secondary hover:border-border-strong cursor-pointer">
                    <span className="material-symbols-outlined text-sm">upload</span>
                    Upload custom
                    <input type="file" accept="image/*" className="hidden" onChange={onFile} />
                </label>
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
            <p className="mt-2 text-xs text-tertiary">
                Whitened, trimmed and placed on the CL2K guides automatically.
            </p>
        </div>
    );
};

// ─── Upload-backdrop tab ────────────────────────────────────────────────────

const UploadBackdropPanel = ({ item, effectiveKind, logos, loadingArt, saveTargets, toast }) => {
    const [file, setFile] = useState(null);
    const [busy, setBusy] = useState(false);
    const [logo, setLogo] = useState(null); // chosen TMDB/fanart logo file_path
    const [customLogo, setCustomLogo] = useState(null); // { b64, name, url }
    const onCustomLogo = useCallback(c => {
        setCustomLogo(c);
        if (c) setLogo(null);
    }, []);

    const submit = useCallback(async () => {
        if (!file) return;
        setBusy(true);
        try {
            const resp = await cl2kMakerAPI.uploadGenerate(file, {
                kind: effectiveKind,
                title: item.title,
                tmdb_id: item.tmdb_id,
                year: item.year,
                tvdb_id: item.tvdb_id,
                imdb_id: item.imdb_id,
                logo_path: customLogo ? null : logo,
                logo_b64: customLogo?.b64 || null,
                ...saveTargets.fields,
            });
            savedToast(toast, resp?.data, 'Generated');
        } catch (err) {
            toast.error(err.message || 'Generate failed');
        } finally {
            setBusy(false);
        }
    }, [file, item, effectiveKind, logo, customLogo, saveTargets.fields, toast]);

    return (
        <section className="mt-4 bg-surface border border-border rounded-lg p-4 flex flex-col gap-3">
            <h3 className="text-sm font-medium text-primary">Cleaned backdrop → render CL2K</h3>
            <p className="text-xs text-tertiary">
                Upload a backdrop you cleaned externally (text removed). CL2K renders the logo,
                gradient and border over it. Leave the logo unset to auto-pick from TMDB/fanart.
            </p>
            <input
                type="file"
                accept="image/*"
                onChange={e => setFile(e.target.files?.[0] || null)}
            />
            <LogoSelector
                label="Logo (TMDB / fanart / custom)"
                logos={logos}
                loading={loadingArt}
                selected={logo}
                onSelect={setLogo}
                customLogo={customLogo}
                onCustomChange={onCustomLogo}
                emptyText="No TMDB/fanart logos — upload a custom one, or leave unset for the text-wordmark fallback."
            />
            <SaveTargets targets={saveTargets} />
            <div>
                <LoadingButton
                    onClick={submit}
                    loading={busy}
                    disabled={!file || saveTargets.noTarget}
                    icon="save"
                >
                    Generate from backdrop
                </LoadingButton>
            </div>
        </section>
    );
};

// ─── Upload finished-poster tab ─────────────────────────────────────────────

const UploadPosterPanel = ({ item, effectiveKind, logos, loadingArt, saveTargets, toast }) => {
    const [file, setFile] = useState(null);
    const [busy, setBusy] = useState(false);
    const [addBorder, setAddBorder] = useState(true);
    const [logo, setLogo] = useState(null); // chosen TMDB/fanart logo file_path
    const [customLogo, setCustomLogo] = useState(null); // { b64, name, url }
    const [previewB64, setPreviewB64] = useState(null); // server-rendered preview
    const [previewing, setPreviewing] = useState(false);
    const localUrl = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
    useEffect(() => () => localUrl && URL.revokeObjectURL(localUrl), [localUrl]);

    // Any input that affects the render also drops a stale server preview, so the
    // shown image never misrepresents the current logo/border.
    const onCustomLogo = useCallback(c => {
        setCustomLogo(c);
        setPreviewB64(null);
        if (c) setLogo(null);
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
        }),
        [effectiveKind, item, addBorder, logo, customLogo]
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
                <img
                    src={shownSrc}
                    alt="Finished poster preview"
                    className="max-h-80 w-auto rounded border border-border bg-black"
                />
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

// ─── G-Drive .psd tab ───────────────────────────────────────────────────────

const GdrivePsdPanel = ({ item, effectiveKind, saveTargets, toast }) => {
    const [drives, setDrives] = useState(null);
    const [driveId, setDriveId] = useState('');
    const [query, setQuery] = useState(item.title || '');
    const [files, setFiles] = useState(null);
    const [loadingFiles, setLoadingFiles] = useState(false);
    const [path, setPath] = useState('');
    const [previewB64, setPreviewB64] = useState(null);
    const [busy, setBusy] = useState(false);
    const [addBorder, setAddBorder] = useState(true);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const resp = await cl2kMakerAPI.gdriveList();
                if (!cancelled) setDrives(resp?.data?.drives || []);
            } catch (err) {
                if (!cancelled) {
                    setDrives([]);
                    toast.error(err.message || 'Failed to load drives');
                }
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [toast]);

    // Search a drive for .psd files matching `q` (case-insensitive substring).
    // The community drives hold hundreds–thousands of PSDs, so we search rather
    // than list everything.
    const search = useCallback(
        async (id, q) => {
            if (!id) return;
            setLoadingFiles(true);
            setPath('');
            setPreviewB64(null);
            try {
                const resp = await cl2kMakerAPI.gdriveList(id, q);
                setFiles(resp?.data?.files || []);
            } catch (err) {
                setFiles([]);
                toast.error(err.message || 'Failed to list .psd files');
            } finally {
                setLoadingFiles(false);
            }
        },
        [toast]
    );

    const onDriveChange = useCallback(
        id => {
            setDriveId(id);
            setFiles(null);
            setPath('');
            setPreviewB64(null);
            // Auto-search for the current title so the matching template surfaces
            // immediately on drive select.
            if (id) search(id, query);
        },
        [search, query]
    );

    const baseReq = useMemo(
        () => ({
            drive_id: driveId,
            path,
            kind: effectiveKind,
            title: item.title,
            tmdb_id: item.tmdb_id,
            year: item.year,
            tvdb_id: item.tvdb_id,
            imdb_id: item.imdb_id,
            border: addBorder,
            // Honoured on save; ignored by the preview branch.
            save_local: saveTargets.saveLocal,
            upload_gdrive: saveTargets.uploadGdrive,
        }),
        [
            driveId,
            path,
            effectiveKind,
            item,
            addBorder,
            saveTargets.saveLocal,
            saveTargets.uploadGdrive,
        ]
    );

    const runPreview = useCallback(async () => {
        if (!path) return;
        setBusy(true);
        try {
            const resp = await cl2kMakerAPI.gdrivePsd({ ...baseReq, preview: true });
            setPreviewB64(resp?.data?.preview_b64 || null);
        } catch (err) {
            toast.error(err.message || 'Preview failed');
        } finally {
            setBusy(false);
        }
    }, [baseReq, path, toast]);

    const runSave = useCallback(async () => {
        if (!path) return;
        setBusy(true);
        try {
            const resp = await cl2kMakerAPI.gdrivePsd({ ...baseReq, preview: false });
            savedToast(toast, resp?.data);
        } catch (err) {
            toast.error(err.message || 'Save failed');
        } finally {
            setBusy(false);
        }
    }, [baseReq, path, toast]);

    const shown = files ? files.slice(0, 200) : [];

    return (
        <section className="mt-4 bg-surface border border-border rounded-lg p-4 flex flex-col gap-3">
            <h3 className="text-sm font-medium text-primary">Drive .psd → flatten</h3>
            {drives === null ? (
                <div className="text-xs text-tertiary">Loading drives…</div>
            ) : drives.length === 0 ? (
                <div className="text-xs text-tertiary">
                    No .psd source drives configured. Add them under{' '}
                    <Link to="/settings/modules" className="text-primary underline">
                        Module Settings → CL2K Maker
                    </Link>{' '}
                    (a subset of your Sync GDrive locations).
                </div>
            ) : (
                <>
                    <label className="flex items-center gap-2 text-sm text-secondary">
                        <span className="w-20">Drive</span>
                        <select
                            value={driveId}
                            onChange={e => onDriveChange(e.target.value)}
                            className="flex-1 bg-surface border border-border rounded px-2 py-1 text-sm text-primary"
                        >
                            <option value="">Select a drive…</option>
                            {drives.map(d => (
                                <option key={d.id} value={d.id}>
                                    {d.name || d.location || d.id}
                                </option>
                            ))}
                        </select>
                    </label>

                    {driveId && (
                        <form
                            onSubmit={e => {
                                e.preventDefault();
                                search(driveId, query);
                            }}
                            className="flex items-center gap-2"
                        >
                            <span className="w-20 text-sm text-secondary">Search</span>
                            <input
                                type="text"
                                value={query}
                                onChange={e => setQuery(e.target.value)}
                                placeholder="Title substring (blank = list all)"
                                className="flex-1 bg-surface border border-border rounded px-2 py-1 text-sm text-primary"
                            />
                            <LoadingButton
                                type="submit"
                                loading={loadingFiles}
                                icon="search"
                                size="small"
                            >
                                Search
                            </LoadingButton>
                        </form>
                    )}

                    {loadingFiles && <div className="text-xs text-tertiary">Searching…</div>}
                    {files && files.length === 0 && !loadingFiles && (
                        <div className="text-xs text-tertiary">
                            No matching .psd files — try a different title or clear the search.
                        </div>
                    )}
                    {files && files.length > 0 && (
                        <div>
                            <div className="text-xs text-tertiary mb-1">
                                {files.length} match{files.length === 1 ? '' : 'es'}
                                {files.length > 200
                                    ? ' — showing first 200, refine your search'
                                    : ''}
                            </div>
                            <div className="max-h-72 overflow-auto border border-border rounded-md divide-y divide-border">
                                {shown.map(f => (
                                    <button
                                        key={f.path}
                                        type="button"
                                        onClick={() => {
                                            setPath(f.path);
                                            setPreviewB64(null);
                                        }}
                                        className={`w-full text-left px-3 py-1.5 text-sm hover:bg-surface-alt ${
                                            path === f.path
                                                ? 'bg-surface-alt text-primary'
                                                : 'text-secondary'
                                        }`}
                                    >
                                        {f.name}
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}

                    {previewB64 && (
                        <img
                            src={`data:image/jpeg;base64,${previewB64}`}
                            alt="PSD preview"
                            className="max-h-80 w-auto rounded border border-border bg-black"
                        />
                    )}

                    <label className="flex items-center gap-2 text-sm text-primary font-medium">
                        <input
                            type="checkbox"
                            checked={addBorder}
                            onChange={e => setAddBorder(e.target.checked)}
                        />
                        Add CL2K white border
                    </label>
                    <p className="text-xs text-tertiary">
                        The DAPS default 26px white frame (per the CL2K PSD). Uncheck only if the
                        .psd already has the required border.
                    </p>

                    <SaveTargets targets={saveTargets} />

                    <div className="flex gap-2">
                        <LoadingButton
                            onClick={runPreview}
                            loading={busy}
                            disabled={!path}
                            variant="secondary"
                            icon="visibility"
                        >
                            Preview
                        </LoadingButton>
                        <LoadingButton
                            onClick={runSave}
                            loading={busy}
                            disabled={!path || saveTargets.noTarget}
                            icon="save"
                        >
                            Flatten &amp; save
                        </LoadingButton>
                    </div>
                </>
            )}
        </section>
    );
};

// ─── Edit poster (AI-erase old text + redraw label in CL2K font) ────────────

const EditPosterPanel = ({ item, effectiveKind, config, saveTargets, toast }) => {
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

    const provider = config?.ai_provider || 'none';
    const isSeason = String(seasonNum).trim() !== '';

    const onFile = useCallback(e => {
        const f = e.target.files?.[0];
        if (!f) return;
        const reader = new FileReader();
        reader.onload = () => {
            setImageDataUrl(reader.result);
            setWorkingB64(String(reader.result).split(',').pop());
            setAiErased(false);
            setMaskB64(null);
            setLabeledB64(null);
        };
        reader.readAsDataURL(f);
    }, []);

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
                ...idFields,
            });
            const erased = resp?.data?.preview_b64;
            if (erased) {
                setWorkingB64(erased);
                setAiErased(true);
                setLabeledB64(null);
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
            {/* Full-width upload bar — keeps the two posters below it top-aligned. */}
            <div className="bg-surface border border-border rounded-lg p-3 flex flex-col gap-2">
                <h3 className="text-sm font-medium text-primary">Edit poster → re-text</h3>
                <p className="text-xs text-tertiary">
                    Upload a finished poster, brush over the old season text and{' '}
                    <span className="text-secondary">Send to AI</span> once to erase it, then
                    position the new label on the working copy — preview and adjust as much as you
                    like for free. Only the erase step uses AI credits. Saved as-is — no CL2K
                    logo/gradient/border added.
                </p>
                <input type="file" accept="image/*" onChange={onFile} />
            </div>

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

                    {/* RIGHT — working copy: position the label, save (no AI) */}
                    <div className="bg-surface border border-border rounded-lg p-3 flex flex-col gap-3">
                        <div className="flex items-center justify-between">
                            <h3 className="text-sm font-medium text-primary">Working copy</h3>
                            {labelBusy && <span className="text-xs text-tertiary">updating…</span>}
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
                                    Upload a poster to start.
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
                            <span className="text-secondary">96% is the locked CL2K default</span> —
                            the season/specials band from the CL2K PSD (y=1440 on the 1500px
                            canvas). Drag for a live preview; it snaps to the exact CL2K render on
                            release.{' '}
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
                            Sets the filename suffix{' '}
                            <code className="text-secondary">_Season{seasonNum || 'NN'}</code> so
                            Poster Renamerr applies it to that season. For year-based shows (F1) use
                            the year (e.g. 2026). Metadata only — it isn’t printed on the poster.
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
                            The DAPS default 26px white frame (per the CL2K PSD). Uncheck only if
                            your uploaded poster already has the required border.
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
                            Saving draws the label and files it (1000×1500, DAPS-named) — no extra
                            AI call.
                        </p>
                    </div>
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
