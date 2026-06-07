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

const Cl2kMakerPage = () => {
    const toast = useToast();
    const [searchParams] = useSearchParams();

    const [config, setConfig] = useState(null);

    // Selected item: { tmdb_id, kind, title, year, tvdb_id, imdb_id } | null.
    // Seeded once from an Unmatched-Assets deep link
    // (?tmdb_id=&type=&title=&year=&tvdb_id=&imdb_id=) when present.
    const [item, setItem] = useState(() => {
        const tmdbId = searchParams.get('tmdb_id');
        if (!tmdbId) return null;
        return {
            tmdb_id: Number(tmdbId),
            kind: normalizeKind(searchParams.get('type')),
            title: searchParams.get('title') || '',
            year: searchParams.get('year') ? Number(searchParams.get('year')) : null,
            tvdb_id: searchParams.get('tvdb_id') ? Number(searchParams.get('tvdb_id')) : null,
            imdb_id: searchParams.get('imdb_id') || null,
        };
    });

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const resp = await configAPI.fetchConfig({ useCache: false });
                if (!cancelled) setConfig(resp?.data?.cl2k_maker || {});
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

            <ConfigBanner config={config} />

            {!item ? (
                <TitlePicker onPick={setItem} toast={toast} />
            ) : (
                <Builder
                    key={`${item.tmdb_id}:${item.kind}`}
                    item={item}
                    config={config}
                    onReset={() => setItem(null)}
                    toast={toast}
                />
            )}
        </div>
    );
};

// ─── Config banner ───────────────────────────────────────────────────────

const ConfigBanner = ({ config }) => {
    if (config === null) return null;
    const missingDir = !config.output_dir;
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
        </section>
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
        r => {
            const title = r.title || r.name || '';
            const dateStr = r.release_date || r.first_air_date || '';
            onPick({
                tmdb_id: r.id,
                kind,
                title,
                year: dateStr ? Number(dateStr.slice(0, 4)) : null,
                tvdb_id: null,
                imdb_id: null,
            });
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
            onPick({
                tmdb_id: Number(tmdbId),
                kind: pasteKind,
                title: '',
                year: null,
                tvdb_id: parsed.source === 'tvdb_id' ? Number(parsed.id) : null,
                imdb_id: parsed.source === 'imdb_id' ? parsed.id : null,
            });
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
                                    className="w-full text-left px-3 py-2 hover:bg-surface-alt flex items-center justify-between gap-3"
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

const Builder = ({ item, config, onReset, toast }) => {
    const [tab, setTab] = useState('tmdb');

    // Art (shared across the TMDB / fanart tabs)
    const [tmdbArt, setTmdbArt] = useState(null);
    const [fanartArt, setFanartArt] = useState(null);
    const [loadingArt, setLoadingArt] = useState(true);
    const [backdrop, setBackdrop] = useState(null); // file_path | absolute url
    const [logo, setLogo] = useState(null);

    // Crop framing: focal point (0..1) for the backdrop cover-crop. 0.5 = centre.
    const [focusX, setFocusX] = useState(0.5);
    const [focusY, setFocusY] = useState(0.5);

    // Season variant (shows only)
    const [seasonNumber, setSeasonNumber] = useState('');
    const [bulkSeasons, setBulkSeasons] = useState('');

    // AI text-removal
    const [removeText, setRemoveText] = useState(false);
    const [maskB64, setMaskB64] = useState(null);
    const [brushSize, setBrushSize] = useState(18);

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
            remove_text: removeText,
            mask_b64: removeText ? maskB64 : null,
            focus_x: focusX,
            focus_y: focusY,
        }),
        [
            effectiveKind,
            item,
            isSeasonPoster,
            seasonNumber,
            backdrop,
            logo,
            removeText,
            maskB64,
            focusX,
            focusY,
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
            toast.success(`Generated: ${resp?.data?.file || 'poster'}`);
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

    return (
        <>
            {/* Selected title bar */}
            <section className="mt-6 p-4 bg-surface border border-border rounded-lg flex items-center justify-between gap-3">
                <div className="min-w-0">
                    <div className="text-lg font-semibold text-primary truncate">
                        {item.title || `TMDB #${item.tmdb_id}`}
                        {item.year ? (
                            <span className="text-tertiary font-normal"> ({item.year})</span>
                        ) : null}
                    </div>
                    <div className="text-xs text-tertiary mt-0.5">
                        {item.kind} · TMDB #{item.tmdb_id}
                        {item.tvdb_id ? ` · TVDB ${item.tvdb_id}` : ''}
                        {item.imdb_id ? ` · ${item.imdb_id}` : ''}
                    </div>
                </div>
                <Button onClick={onReset} variant="secondary" icon="arrow_back">
                    Change title
                </Button>
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
                />
            )}

            {tab === 'upload-backdrop' && (
                <UploadBackdropPanel item={item} effectiveKind={effectiveKind} toast={toast} />
            )}
            {tab === 'upload-poster' && (
                <UploadPosterPanel item={item} effectiveKind={effectiveKind} toast={toast} />
            )}
            {tab === 'gdrive-psd' && (
                <GdrivePsdPanel item={item} effectiveKind={effectiveKind} toast={toast} />
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

                <Picker
                    label={`Logo (${source})`}
                    items={logos}
                    loading={loadingArt}
                    selected={logo}
                    onSelect={setLogo}
                    aspect="aspect-video"
                    onBlack
                    emptyText="No logos from this source — a text wordmark is used as fallback."
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
                    <LoadingButton
                        onClick={onGenerate}
                        loading={busy}
                        disabled={!backdrop}
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

// ─── Upload-backdrop tab ────────────────────────────────────────────────────

const UploadBackdropPanel = ({ item, effectiveKind, toast }) => {
    const [file, setFile] = useState(null);
    const [busy, setBusy] = useState(false);

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
            });
            toast.success(`Generated: ${resp?.data?.file || 'poster'}`);
        } catch (err) {
            toast.error(err.message || 'Generate failed');
        } finally {
            setBusy(false);
        }
    }, [file, item, effectiveKind, toast]);

    return (
        <section className="mt-4 bg-surface border border-border rounded-lg p-4 flex flex-col gap-3">
            <h3 className="text-sm font-medium text-primary">Cleaned backdrop → render CL2K</h3>
            <p className="text-xs text-tertiary">
                Upload a backdrop you cleaned externally (text removed). CL2K renders the logo,
                gradient and border over it.
            </p>
            <input
                type="file"
                accept="image/*"
                onChange={e => setFile(e.target.files?.[0] || null)}
            />
            <div>
                <LoadingButton onClick={submit} loading={busy} disabled={!file} icon="save">
                    Generate from backdrop
                </LoadingButton>
            </div>
        </section>
    );
};

// ─── Upload finished-poster tab ─────────────────────────────────────────────

const UploadPosterPanel = ({ item, effectiveKind, toast }) => {
    const [file, setFile] = useState(null);
    const [busy, setBusy] = useState(false);
    const localUrl = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
    useEffect(() => () => localUrl && URL.revokeObjectURL(localUrl), [localUrl]);

    const submit = useCallback(async () => {
        if (!file) return;
        setBusy(true);
        try {
            const resp = await cl2kMakerAPI.uploadPoster(file, {
                kind: effectiveKind,
                title: item.title,
                tmdb_id: item.tmdb_id,
                year: item.year,
                tvdb_id: item.tvdb_id,
                imdb_id: item.imdb_id,
            });
            toast.success(`Saved: ${resp?.data?.file || 'poster'}`);
        } catch (err) {
            toast.error(err.message || 'Save failed');
        } finally {
            setBusy(false);
        }
    }, [file, item, effectiveKind, toast]);

    return (
        <section className="mt-4 bg-surface border border-border rounded-lg p-4 flex flex-col gap-3">
            <h3 className="text-sm font-medium text-primary">Finished poster → file as-is</h3>
            <p className="text-xs text-tertiary">
                Upload a complete poster. It&apos;s stored unchanged (only DAPS-named) and
                registered so the rest of CHUB picks it up.
            </p>
            <input
                type="file"
                accept="image/*"
                onChange={e => setFile(e.target.files?.[0] || null)}
            />
            {localUrl && (
                <img
                    src={localUrl}
                    alt="Finished poster preview"
                    className="max-h-80 w-auto rounded border border-border bg-black"
                />
            )}
            <div>
                <LoadingButton onClick={submit} loading={busy} disabled={!file} icon="save">
                    Save poster
                </LoadingButton>
            </div>
        </section>
    );
};

// ─── G-Drive .psd tab ───────────────────────────────────────────────────────

const GdrivePsdPanel = ({ item, effectiveKind, toast }) => {
    const [drives, setDrives] = useState(null);
    const [driveId, setDriveId] = useState('');
    const [query, setQuery] = useState(item.title || '');
    const [files, setFiles] = useState(null);
    const [loadingFiles, setLoadingFiles] = useState(false);
    const [path, setPath] = useState('');
    const [previewB64, setPreviewB64] = useState(null);
    const [busy, setBusy] = useState(false);

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
        }),
        [driveId, path, effectiveKind, item]
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
            toast.success(`Saved: ${resp?.data?.file || 'poster'}`);
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
                            disabled={!path}
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

export default Cl2kMakerPage;
