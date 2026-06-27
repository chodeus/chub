import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { cl2kMakerAPI } from '../../utils/api/cl2k_maker.js';
import { configAPI } from '../../utils/api/config.js';
import { postersAPI } from '../../utils/api/posters.js';
import { posterSelfHealAPI } from '../../utils/api/posterSelfHeal.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { Button, LoadingButton, PageHeader, Toggle } from '../../components/ui/index.js';
import SegmentedControl from '../../components/ui/SegmentedControl.jsx';
import Spinner from '../../components/ui/Spinner.jsx';

// Small self-contained badge: shows "N posters need review" linking to the
// Poster Healer review page, only when the healer has open proposals. Lives here
// so the CL2K page surfaces healer work without threading state through the page.
const HealReviewLink = () => {
    const [count, setCount] = useState(0);
    useEffect(() => {
        posterSelfHealAPI
            .count()
            .then(r => setCount(r?.data?.count || 0))
            .catch(() => {});
    }, []);
    if (!count) return null;
    return (
        <Link to="/poster/heal-review" className="font-medium text-warning hover:underline">
            {count} poster{count === 1 ? '' : 's'} need review →
        </Link>
    );
};

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
// "Specials" is NOT here — it's a season (0), made via the Season box, which both
// files as `- Specials` and renders the SPECIALS label.
const BAND_LABEL_OPTIONS = [
    { value: '', label: 'None' },
    { value: 'COMPLETE LIMITED SERIES', label: 'Complete Limited Series' },
];

// Wordmark logos first. TMDB's "logos" array is polluted with portrait
// character art (full-body Goku/Vegeta/etc. renders) that whiten into line-art
// garbage and render tiny in the landscape CL2K logo zone. Real title wordmarks
// are wide (aspect ≳ 1.4); push tall/portrait images to the end. Stable within
// each group; unknown-dimension logos (fanart/Plex clearlogos — already proper
// wordmarks) rank with the wordmarks. Hides nothing — just orders. Shared by the
// Builder source pickers and the merged asset-tab lists.
const sortWordmarkFirst = logos =>
    logos
        .map((l, i) => [l, i])
        .sort(([a, ai], [b, bi]) => {
            const score = x => (x.width && x.height && x.width / x.height < 1.4 ? 1 : 0);
            return score(a) - score(b) || ai - bi;
        })
        .map(([l]) => l);

// Top-level tabs = WHAT you're building. Sources (TMDB/fanart/Plex/Upload) are
// chosen per-picker inside each page (see SourceSelector).
const BUILD_TABS = [
    { key: 'poster', label: 'Poster', icon: 'image', ar: '2:3' },
    { key: 'background', label: 'Background', icon: 'wallpaper', ar: '16:9' },
    { key: 'square', label: 'Square art', icon: 'crop_square', ar: '1:1' },
    { key: 'logo', label: 'Logo', icon: 'sell', ar: 'logo' },
];
// Retired tab keys (source-as-tab, the Finished-poster tab, and the removed
// Edit-poster / upload-backdrop tabs) → the unified 'poster' build tab, so a
// saved session migrates instead of landing on a tab that no longer exists.
// Editing a finished poster — G-Drive pick or manual upload — all lives in the
// Poster tab now, so there's no separate Edit-poster tab.
const TAB_MIGRATE = {
    tmdb: 'poster',
    fanart: 'poster',
    plex: 'poster',
    'upload-poster': 'poster',
    'upload-backdrop': 'poster',
    edit: 'poster',
};

// Per-picker artwork sources (Option A: a segmented row in each picker header).
// 'upload' swaps the grid for that picker's custom-upload control.
const ART_SOURCES = [
    { key: 'tmdb', label: 'TMDB', icon: 'movie' },
    { key: 'fanart', label: 'fanart', icon: 'palette' },
    { key: 'plex', label: 'Plex', icon: 'live_tv' },
    { key: 'upload', label: 'Upload', icon: 'upload' },
];

// The Poster tab's backdrop picker adds a 'gdrive' source (browse the GDrive sync
// cache) on top of ART_SOURCES — kept Poster-only so the logo / background /
// square pickers don't grow a meaningless "grab a finished poster" option.
const BACKDROP_SOURCES = [...ART_SOURCES, { key: 'gdrive', label: 'GDrive', icon: 'cloud_sync' }];

// Stable identity for an uploaded image ({ b64, name }) in change-detection
// signatures. A b64-prefix slice can collide: the first ~24 bytes of a JPEG are
// a format header that different files from the same exporter share.
const customSig = c => (c ? `${c.name}:${c.b64?.length || 0}` : null);

const SourceSelector = ({ value, onChange, sources = ART_SOURCES }) => (
    <div className="flex items-center gap-1 flex-wrap">
        {sources.map(s => (
            <button
                key={s.key}
                type="button"
                onClick={() => onChange(s.key)}
                className={`inline-flex items-center gap-1 px-2 py-1 text-xs rounded-md border ${
                    value === s.key
                        ? 'bg-primary text-white border-primary'
                        : 'bg-surface text-fg-muted border-border hover:border-primary'
                }`}
                title={s.label}
            >
                <span className="material-symbols-outlined text-sm">{s.icon}</span>
                {s.label}
            </button>
        ))}
    </div>
);

// Map a deep-link / paste media type onto the kind strings the maker uses.
const normalizeKind = t => {
    const v = (t || '').toLowerCase();
    if (v === 'movie') return 'movie';
    if (v === 'collection') return 'collection';
    if (v === 'tv' || v === 'series' || v === 'show') return 'show';
    return 'movie';
};

// ─── ID / URL paste parsing ──────────────────────────────────────────────
// Accepts a bare id, an explicit `tvdb:<id>` tag, or a TMDB / TVDB / IMDB url.
// Returns {source, id} where source is 'tmdb' (resolve not needed) or
// 'tvdb_id' / 'imdb_id' (needs resolve), or {error} for a recognised-but-
// unusable input (a slug-only thetvdb.com URL carries no numeric id).
const parsePastedId = raw => {
    const s = (raw || '').trim();
    if (!s) return null;
    const imdb = s.match(/(tt\d{6,})/i);
    if (imdb) return { source: 'imdb_id', id: imdb[1] };
    const tmdbUrl = s.match(/themoviedb\.org\/(movie|tv|collection)\/(\d+)/i);
    if (tmdbUrl) return { source: 'tmdb', id: tmdbUrl[2], type: normalizeKind(tmdbUrl[1]) };
    // Explicit tvdb tag: `tvdb:413715`, `tvdb-413715`, `tvdb 413715`, `tvdb_id=413715`.
    const tvdbTag = s.match(/^tvdb(?:_id)?[\s:=-]+(\d+)$/i);
    if (tvdbTag) return { source: 'tvdb_id', id: tvdbTag[1] };
    if (/thetvdb\.com/i.test(s)) {
        // Numeric TVDB url forms only: ?id=/&seriesid=, or /series|/movies/<digits>.
        // Modern slug urls (/series/<name>) carry no number — flag those so the
        // caller can tell the user to paste the numeric Series ID instead.
        const tvdbUrl = s.match(/(?:[?&](?:id|seriesid)=|\/(?:series|movies)\/)(\d+)/i);
        if (tvdbUrl) return { source: 'tvdb_id', id: tvdbUrl[1] };
        return { error: 'tvdb_slug' };
    }
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
// Bottom baselines verified against the PSDs in refs/ (template + finished
// posters all bottom-align their LOGO layer at exactly these guides).
const CL2K_LOGO_BASELINE_MAIN = 1352; // geo.MAIN_LOGO_BOTTOM ("Main Logo Bottom")
const CL2K_LOGO_BASELINE_COLLECTION = 1319; // geo.COLLECTION_LOGO_BOTTOM
const CL2K_LOGO_WIDTH_MAX = 800; // geo.LOGO_WIDTH_MAX (guide line, not a clamp)
const CL2K_LOGO_ZONE_TOP = 1100; // geo.LOGO_ZONE_TOP ("Main Logo Height")
// Slider/clamp ranges — mirror of geometry.py's interactive control ranges (the
// backend pydantic Field/Form ge/le validate against the same numbers). Keep in
// sync with backend/util/cl2k/geometry.py.
const CONTROL_RANGES = {
    logoScale: { min: 0.25, max: 3 }, // geo.LOGO_SCALE_MIN/MAX
    logoYOffset: { min: -600, max: 200 }, // geo.LOGO_Y_OFFSET_MIN/MAX
    zoom: { min: 0.5, max: 3 }, // geo.ZOOM_MIN/MAX
};

const cl2kLogoBaseline = kind =>
    (kind || '').toLowerCase() === 'collection'
        ? CL2K_LOGO_BASELINE_COLLECTION
        : CL2K_LOGO_BASELINE_MAIN;

// natW/natH = trimmed logo dims (from /logo-processed); maxWidth = the
// recommended guide-box width the backend reports (700px); baseline = the
// kind's bottom guide (geo.logo_baseline mirror).
// Returns the overlay box as percentages of the 2:3 preview, or null.
const logoBoxPct = ({ natW, natH, maxWidth, scale = 1, yOffset = 0, baseline }) => {
    if (!natW || !natH) return null;
    const base = baseline || CL2K_LOGO_BASELINE_MAIN;
    const s = Math.max(
        CONTROL_RANGES.logoScale.min,
        Math.min(scale || 1, CONTROL_RANGES.logoScale.max)
    );
    const off = Math.max(
        CONTROL_RANGES.logoYOffset.min,
        Math.min(Math.round(yOffset || 0), CONTROL_RANGES.logoYOffset.max)
    );
    let targetW = Math.min(maxWidth || 700, CL2K_LOGO_WIDTH_MAX);
    let targetH = Math.round((natH * targetW) / natW);
    const maxH = base - CL2K_LOGO_ZONE_TOP;
    if (targetH > maxH) {
        targetH = maxH;
        targetW = Math.round((natW * targetH) / natH);
    }
    // Scale the guide-fit box as a whole; keep it on the canvas (aspect kept) —
    // mirrors _place_logo so the overlay still lands pixel-exact. The width
    // guides are guidelines only, not a clamp.
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
    let top = base - targetH + off;
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
// height, maxWidth } from /logo-processed; `kind` picks the bottom baseline
// (collection logos sit on the higher 1319 guide).
const LogoOverlay = ({ logo, scale, yOffset, kind }) => {
    if (!logo?.dataUrl) return null;
    const box = logoBoxPct({
        natW: logo.width,
        natH: logo.height,
        maxWidth: logo.maxWidth,
        scale,
        yOffset,
        baseline: cl2kLogoBaseline(kind),
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

// Dim + spinner over a stale preview while its replacement renders server-side.
// Without this the old image just sits there until the new one pops in, which
// reads as "the slider did nothing". Inline styles — must not depend on utility
// classes existing.
const PreviewRefreshing = ({ active }) => {
    if (!active) return null;
    return (
        <div
            style={{
                position: 'absolute',
                inset: 0,
                background: 'rgba(0, 0, 0, 0.35)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                pointerEvents: 'none',
            }}
            aria-hidden="true"
        >
            <Spinner size="small" />
        </div>
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
        const tvdbId = searchParams.get('tvdb_id');
        const imdbId = searchParams.get('imdb_id');
        // A deep link carries any of tmdb/tvdb/imdb. A TVDB/IMDB-only link — e.g.
        // an unmatched Sonarr show TMDB has no cross-link for — seeds with a null
        // tmdb_id; the resolve-on-entry effect below fills it when a match exists.
        if (tmdbId || tvdbId || imdbId) {
            // A fresh deep link is a new title — drop any stale builder snapshot.
            ssRemove(SS_BUILDER);
            return {
                tmdb_id: tmdbId ? Number(tmdbId) : null,
                kind: normalizeKind(searchParams.get('type')),
                title: searchParams.get('title') || '',
                year: searchParams.get('year') ? Number(searchParams.get('year')) : null,
                tvdb_id: tvdbId ? Number(tvdbId) : null,
                imdb_id: imdbId || null,
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

    // A TVDB/IMDB-only entry (deep link, or a paste TMDB has no cross-link for)
    // carries no tmdb_id, so the TMDB art picker comes back empty. Resolve one in
    // the background and patch it in when TMDB has the link — unlocking the full
    // TMDB/fanart picker. A miss is harmless (Plex art + Edit IDs still work).
    // Runs once per id-set and never clobbers an existing tmdb_id.
    const idResolveProbe = useRef(null);
    useEffect(() => {
        idResolveProbe.current = null;
    }, [selectionKey]);
    useEffect(() => {
        if (!item || item.tmdb_id || item.kind === 'collection') return undefined;
        const ext = item.tvdb_id
            ? { id: item.tvdb_id, source: 'tvdb_id' }
            : item.imdb_id
              ? { id: item.imdb_id, source: 'imdb_id' }
              : null;
        if (!ext) return undefined;
        const sig = `${ext.source}:${ext.id}`;
        if (idResolveProbe.current === sig) return undefined;
        idResolveProbe.current = sig;
        let cancelled = false;
        (async () => {
            try {
                const resp = await cl2kMakerAPI.resolve(String(ext.id), ext.source, item.kind);
                const tmdbId = resp?.data?.tmdb_id;
                if (!cancelled && tmdbId) {
                    setItem(prev =>
                        prev && !prev.tmdb_id ? { ...prev, tmdb_id: Number(tmdbId) } : prev
                    );
                }
            } catch {
                /* leave tmdb_id null — Plex/fanart by tvdb + Edit IDs still work */
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
        <div className="cl2k-page p-4 md:p-6 pb-24">
            {/* Brand-styled range sliders (mock spec) — scoped to this page so
                it stays develop-only and doesn't touch shared CSS. */}
            <style>{`
.cl2k-page input[type=range]{-webkit-appearance:none;appearance:none;height:5px;border-radius:3px;background:#2a3052;accent-color:var(--primary);cursor:pointer;}
.cl2k-page input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:15px;height:15px;border-radius:50%;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.5);cursor:pointer;}
.cl2k-page input[type=range]::-moz-range-thumb{width:15px;height:15px;border:none;border-radius:50%;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.5);cursor:pointer;}
`}</style>
            <PageHeader
                title="CL2K Poster Maker"
                description="Turn a TMDB/TVDB/IMDB title into a DAPS-named CL2K asset — the full 4-asset studio"
                actions={
                    <span className="font-mono text-[10px] tracking-[0.6px] px-2.5 py-1 rounded-md bg-accent/12 text-accent self-center">
                        DEVELOP
                    </span>
                }
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
        <>
            {/* Config strip — the non-visual knobs live in Module Settings; the
                output dir is shown read-only (styled like the mock's field) since
                there's no inline-save backend, with a link back to edit it. */}
            <section className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-[11px] bg-surface border border-border rounded-[10px] text-[12.5px]">
                <span className="flex items-center gap-[7px] text-fg-subtle">
                    Output dir
                    <span
                        className={`inline-flex items-center h-7 px-2.5 rounded-md bg-surface-inset border font-mono text-[11.5px] ${
                            missingDir ? 'border-error text-error' : 'border-border text-fg-muted'
                        }`}
                    >
                        {config.output_dir || 'not set'}
                    </span>
                </span>
                <span className="text-fg-subtle">
                    Whiten logo{' '}
                    <span className={config.whiten_logo ? 'text-success' : 'text-fg-muted'}>
                        {config.whiten_logo ? 'yes' : 'no'}
                    </span>
                </span>
                <span className="text-fg-subtle">
                    AI provider{' '}
                    <span className="text-fg-muted">{config.ai_provider || 'none'}</span>
                </span>
                <HealReviewLink />
                <Link
                    to="/settings/modules/cl2k_maker"
                    className="ml-auto font-medium text-accent hover:underline"
                >
                    Edit in Module Settings →
                </Link>
            </section>

            {missingDir && (
                <div className="mt-2.5 flex items-center gap-2.5 px-3.5 py-2.5 rounded-[9px] bg-error/10 border border-error/30">
                    <span className="material-symbols-outlined text-error text-[17px] shrink-0">
                        warning
                    </span>
                    <span className="text-[12.5px] text-fg-muted">
                        Output directory not set — saves will fail.{' '}
                        <Link
                            to="/settings/modules/cl2k_maker"
                            className="text-error hover:underline"
                        >
                            Set it in Module Settings.
                        </Link>
                    </span>
                </div>
            )}
            {uploadNoToken && (
                <div className="mt-2.5 flex items-center gap-2.5 px-3.5 py-2.5 rounded-[9px] bg-warning/10 border border-warning/30">
                    <span className="material-symbols-outlined text-warning text-[17px] shrink-0">
                        warning
                    </span>
                    <span className="text-[12.5px] text-fg-muted">
                        Google Drive upload enabled but no OAuth token — uploads will fail, local
                        save still works.{' '}
                        <Link
                            to="/settings/modules/cl2k_maker"
                            className="text-warning hover:underline"
                        >
                            Connect Drive →
                        </Link>
                    </span>
                </div>
            )}
        </>
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
            <span className="text-xs font-medium text-fg-muted">Save to</span>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
                <label className="flex items-center gap-2 text-sm text-fg">
                    <input
                        type="checkbox"
                        checked={saveLocal}
                        onChange={e => setSaveLocal(e.target.checked)}
                    />
                    Output directory
                </label>
                <label
                    className={`flex items-center gap-2 text-sm text-fg ${
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
                <p className="text-xs text-fg-subtle">
                    Set a Drive folder under{' '}
                    <Link to="/settings/modules/cl2k_maker" className="text-fg underline">
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
        if (parsed?.error === 'tvdb_slug') {
            toast.error(
                "TheTVDB page URLs use a name slug, not a number. Open the page and paste the numeric 'Series ID' shown there, type tvdb:<id>, or search by title above."
            );
            return;
        }
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
            const tvdbId = parsed.source === 'tvdb_id' ? Number(parsed.id) : null;
            const imdbId = parsed.source === 'imdb_id' ? parsed.id : null;
            // No TMDB entry is cross-linked to this external id (common for smaller
            // TVDB-keyed shows)? Open the builder anyway with the id set — Plex /
            // fanart art and the Edit IDs panel still work — instead of dead-ending.
            if (!tmdbId) {
                toast.info(
                    'No TMDB entry is linked to that id — opened with the ID set. Search by title above, or add a title in Edit IDs.'
                );
            }
            const base = {
                tmdb_id: tmdbId ? Number(tmdbId) : null,
                kind: pasteKind,
                title: '',
                year: null,
                tvdb_id: tvdbId,
                imdb_id: imdbId,
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

    const inputCls =
        'flex-1 min-w-0 h-[42px] px-3.5 rounded-lg bg-surface-inset border border-border text-fg text-sm outline-none focus:border-primary transition-colors placeholder:text-fg-dim';

    return (
        <section
            className="mt-6 mx-auto w-full max-w-[640px] bg-surface border border-border rounded-xl p-5"
            style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
        >
            <h2 className="font-display text-[17px] font-semibold text-fg mb-3.5">Pick a title</h2>

            <div className="mb-3.5">
                <SegmentedControl
                    size="sm"
                    options={KIND_OPTIONS}
                    value={kind}
                    onChange={setKind}
                />
            </div>

            <form onSubmit={runSearch} className="flex gap-2 mb-1.5">
                <input
                    type="text"
                    value={query}
                    onChange={e => setQuery(e.target.value)}
                    placeholder="Search TMDB by title…"
                    className={inputCls}
                />
                <button
                    type="submit"
                    disabled={searching}
                    className="h-[42px] px-[18px] rounded-lg bg-primary text-on-color font-display text-[13.5px] font-semibold hover:brightness-110 disabled:opacity-60 transition"
                >
                    {searching ? 'Searching…' : 'Search'}
                </button>
            </form>
            <p className="text-[11.5px] text-fg-dim mb-3">
                Try: dune, severance, shogun, oppenheimer…
            </p>

            {results.length > 0 && (
                <div className="border border-border rounded-lg overflow-hidden mb-4 max-h-80 overflow-y-auto">
                    {results.map(r => {
                        const title = r.title || r.name || '(untitled)';
                        const date = r.release_date || r.first_air_date || '';
                        return (
                            <button
                                key={r.id}
                                type="button"
                                onClick={() => pickResult(r)}
                                disabled={picking}
                                className={`w-full text-left px-3.5 py-2.5 flex items-center justify-between gap-3 border-b border-border-light last:border-0 hover:bg-row-hover transition-colors ${
                                    picking ? 'opacity-60 cursor-wait' : ''
                                }`}
                            >
                                <span className="text-sm text-fg truncate">{title}</span>
                                <span className="font-mono text-[11.5px] text-fg-subtle shrink-0">
                                    {date ? date.slice(0, 4) : '—'} · #{r.id}
                                </span>
                            </button>
                        );
                    })}
                </div>
            )}

            <div className="border-t border-border pt-3.5">
                <p className="text-[12.5px] text-fg-subtle mb-2.5">
                    …or paste a TMDB / TVDB / IMDB ID or URL
                </p>
                <div className="flex gap-2">
                    <input
                        type="text"
                        value={paste}
                        onChange={e => setPaste(e.target.value)}
                        placeholder="e.g. 603, tt0133093, tvdb:413715, or a TMDB/TVDB URL"
                        className={`${inputCls} h-10 font-mono text-[13px]`}
                    />
                    <button
                        type="button"
                        onClick={runPaste}
                        disabled={resolving}
                        className="h-10 px-4 rounded-lg bg-surface-inset border border-border text-fg-muted text-[13px] font-semibold hover:bg-row-hover hover:text-fg disabled:opacity-60 transition"
                    >
                        {resolving ? 'Resolving…' : 'Use ID'}
                    </button>
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
    const inputCls = 'flex-1 bg-surface border border-border rounded px-2 py-1 text-sm text-fg';
    const row = (lbl, el) => (
        <label className="flex items-center gap-2 text-sm text-fg-muted">
            <span className="w-16 shrink-0">{lbl}</span>
            {el}
        </label>
    );
    return (
        <div className="mt-3 pt-3 border-t border-border-subtle flex flex-col gap-2">
            <p className="text-xs text-fg-subtle">
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
    const [searchParams] = useSearchParams();

    // Migrate retired tab keys to the unified 'poster' build tab (see TAB_MIGRATE)
    // so a saved session never lands on a tab that no longer exists. A deep link
    // from Unmatched → Additional artwork carries ?asset=<tab> so the maker opens
    // on the right asset tab (background / square / logo) ready to build it.
    const [tab, setTab] = useState(() => {
        const assetParam = searchParams.get('asset');
        if (assetParam && BUILD_TABS.some(t => t.key === assetParam)) return assetParam;
        const t = saved.tab ?? 'poster';
        return TAB_MIGRATE[t] || t;
    });
    const [editIds, setEditIds] = useState(false);

    // Save destinations (output dir / Drive) — shared by every save flow below.
    const saveTargets = useSaveTargets(uploadStatus);

    // Art (shared across the TMDB / fanart / Plex tabs)
    const [tmdbArt, setTmdbArt] = useState(null);
    const [fanartArt, setFanartArt] = useState(null);
    const [plexArt, setPlexArt] = useState(null);
    // TMDB season-level posters (portrait 2:3) — only for season posters.
    const [seasonArt, setSeasonArt] = useState(null);
    const [loadingArt, setLoadingArt] = useState(true);
    const [backdrop, setBackdrop] = useState(saved.backdrop ?? null); // file_path | absolute url
    const [logo, setLogo] = useState(saved.logo ?? null);
    // Per-picker sources on the Poster page (persisted so a restored fanart/plex
    // selection comes back with its own grid showing, not an unhighlighted TMDB).
    const [backdropSource, setBackdropSource] = useState(saved.backdropSource ?? 'tmdb');
    const [logoSource, setLogoSource] = useState(saved.logoSource ?? 'tmdb');
    // Custom uploaded logo (one-off, not persisted): { b64, name, url }. When set
    // it overrides the chosen TMDB/fanart `logo` path.
    const [customLogo, setCustomLogo] = useState(null);
    const setCustomLogoExclusive = useCallback(c => {
        setCustomLogo(c);
        if (c) setLogo(null); // custom logo replaces a chosen TMDB/fanart logo
    }, []);
    // Custom uploaded backdrop (the 'Upload' backdrop source): { b64, name, url }.
    // Mutually exclusive with a picker-chosen `backdrop` path.
    const [customBackdrop, setCustomBackdrop] = useState(null);
    const setBackdropExclusive = useCallback(p => {
        setBackdrop(p);
        if (p) setCustomBackdrop(null);
    }, []);
    const setCustomBackdropExclusive = useCallback(c => {
        setCustomBackdrop(c);
        if (c) setBackdrop(null);
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
    // Invert logo: white -> transparent, black -> white (plate/sticker art).
    const [invertLogo, setInvertLogo] = useState(saved.invertLogo ?? false);

    // Season variant (shows only)
    const [seasonNumber, setSeasonNumber] = useState(saved.seasonNumber ?? '');
    const [bulkSeasons, setBulkSeasons] = useState(saved.bulkSeasons ?? '');
    // Optional bottom banner (e.g. COMPLETE LIMITED SERIES). Overrides the auto
    // COLLECTION / season label — including on a season poster, so a limited
    // series can show COMPLETE LIMITED SERIES in place of SEASON N (the file is
    // still saved as `- Season NN`). Drop a stale saved value no longer in the
    // options (e.g. the retired "SPECIALS", now made via Season 0) so it can't
    // silently re-apply.
    const [bandLabel, setBandLabel] = useState(() =>
        BAND_LABEL_OPTIONS.some(o => o.value === saved.bandLabel) ? saved.bandLabel : ''
    );

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
            backdropSource,
            logoSource,
            fitMode,
            crop,
            vPos,
            zoom,
            focusX,
            focusY,
            logoScale,
            logoYOffset,
            whitenLogo,
            invertLogo,
            seasonNumber,
            bulkSeasons,
            bandLabel,
            removeText,
        });
    }, [
        tab,
        backdrop,
        logo,
        backdropSource,
        logoSource,
        fitMode,
        crop,
        vPos,
        zoom,
        focusX,
        focusY,
        logoScale,
        logoYOffset,
        whitenLogo,
        invertLogo,
        seasonNumber,
        bulkSeasons,
        bandLabel,
        removeText,
    ]);

    // Preview
    const [previewUrl, setPreviewUrl] = useState(null);
    const [previewing, setPreviewing] = useState(false);
    const [busy, setBusy] = useState(false);
    // Live "n/total" readout while a background season batch runs (see runBulkSeasons).
    const [bulkProgress, setBulkProgress] = useState('');

    // A real (chosen/custom) logo is drawn as a live overlay on the logo-less base
    // so the size/position sliders move it without a server render. No logo = a
    // text wordmark, which is baked into the base instead (can't overlay it).
    //
    // Two processed variants: `processedBase` (no touch-up) is the STABLE image
    // the B/W touch-up brush draws over — it must not change as strokes land, or
    // the accumulated mask would be lost; `processedLogo` (touch-up applied) is
    // what the live overlay shows and the render bakes in.
    const hasLogo = !!(logo || customLogo);
    // Strokes are keyed to the (logo, whiten, invert) they were drawn over: a
    // stale key makes the mask a derived no-op instead of needing a reset-in-effect.
    const flipKey = `${customSig(customLogo) || logo}|${effectiveWhiten}|${invertLogo}`;
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
                    invert: invertLogo,
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
        [customLogo, logo, effectiveWhiten, invertLogo]
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

    // Picking a banner (e.g. COMPLETE LIMITED SERIES) on a show with no season
    // number defaults it to Season 1: that banner belongs on the limited series'
    // season poster, so this saves it to the season slot rather than the main
    // show poster. An explicit season number is never overridden, and clearing
    // the season afterwards keeps the banner — a main-poster banner stays
    // possible.
    const onBandLabel = useCallback(
        value => {
            setBandLabel(value);
            if (value && item.kind === 'show' && String(seasonNumber).trim() === '') {
                setSeasonNumber('1');
            }
        },
        [item.kind, seasonNumber]
    );

    // Load TMDB + fanart art. Builder is keyed by item, so selection/art state
    // starts fresh on each item — no synchronous resets needed here.
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const [tm, fa, px] = await Promise.allSettled([
                    cl2kMakerAPI.images(item.tmdb_id, item.kind),
                    cl2kMakerAPI.fanartImages({
                        tmdbId: item.tmdb_id,
                        type: item.kind,
                        tvdbId: item.tvdb_id,
                        imdbId: item.imdb_id,
                    }),
                    // Read-only: resolves via the synced plex cache, returns empty
                    // (with a reason) when Plex isn't configured or the item isn't
                    // in a library. Fetched eagerly so it's also in the merged
                    // asset-tab lists, not just the Plex source tab.
                    cl2kMakerAPI.plexImages({
                        tmdbId: item.tmdb_id,
                        type: item.kind,
                        tvdbId: item.tvdb_id,
                        imdbId: item.imdb_id,
                    }),
                ]);
                if (cancelled) return;
                if (tm.status === 'fulfilled') setTmdbArt(tm.value?.data || null);
                if (fa.status === 'fulfilled') setFanartArt(fa.value?.data || null);
                if (px.status === 'fulfilled') setPlexArt(px.value?.data || null);
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
            backdrop_path: customBackdrop ? null : backdrop,
            backdrop_b64: customBackdrop?.b64 || null,
            logo_path: logo,
            logo_b64: customLogo?.b64 || null,
            logo_scale: logoScale,
            logo_y_offset: logoYOffset,
            whiten: whitenLogo,
            invert: invertLogo,
            logo_flip_b64: logoFlipB64,
            // AI text-removal is an explicit step now — the "Send to AI" button
            // erases the masked text and bakes the cleaned art into the backdrop.
            // Render/generate must NEVER run AI themselves, or a checked box with
            // no mask triggers a destructive maskless whole-poster regeneration.
            remove_text: false,
            mask_b64: null,
            fit_mode: fitMode,
            focus_x: focusX,
            focus_y: focusY,
            crop_x: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.x : null,
            crop_y: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.y : null,
            crop_w: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.w : null,
            crop_h: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.h : null,
            // v_pos applies to every mode now (Fill pans up; fit/extend position).
            v_pos: vPos,
            zoom: zoom,
            // Banner overrides the auto COLLECTION / SEASON label — e.g. a season
            // poster drawing COMPLETE LIMITED SERIES in place of SEASON N.
            band_label: bandLabel,
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
            customBackdrop,
            logo,
            customLogo,
            logoScale,
            logoYOffset,
            whitenLogo,
            invertLogo,
            logoFlipB64,
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
    // identity a trigger (the effect fires off baseSig, below). The debounce
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
                cbd: customSig(customBackdrop),
                fm: fitMode,
                c: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop : null,
                vp: vPos,
                zm: zoom,
                fx: focusX,
                fy: focusY,
                bl: bandLabel,
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
            customBackdrop,
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
        if (tab !== 'poster') return undefined;
        // No art chosen yet (picker path or custom upload) — nothing to render.
        if (!backdrop && !customBackdrop) return undefined;
        let cancelled = false;
        const aborter = new AbortController();
        const handle = setTimeout(async () => {
            setPreviewing(true);
            try {
                const blob = await cl2kMakerAPI.preview(
                    {
                        ...baseRequestRef.current,
                        place_logo: !hasLogo,
                        remove_text: false,
                        mask_b64: null,
                    },
                    { signal: aborter.signal }
                );
                if (!cancelled) setPreview(blob);
            } catch {
                /* auto-render stays quiet; the Refresh button surfaces errors */
            } finally {
                if (!cancelled) setPreviewing(false);
            }
        }, 300);
        return () => {
            cancelled = true;
            aborter.abort();
            clearTimeout(handle);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [baseSig]);

    // Manual full refresh: re-render from current inputs (no AI — text-removal is
    // the separate "Send to AI" step, baked into the backdrop). Bake the logo only
    // for the text-wordmark fallback (a chosen logo stays a live overlay so the
    // sliders keep moving it).
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
        if (!backdrop && !customBackdrop) {
            toast.error('Pick a backdrop first — seasons reuse the poster you built.');
            return;
        }
        setBusy(true);
        setBulkProgress(`0/${nums.length}`);
        try {
            // The seasons reuse the SAME backdrop + logo the user built in the
            // preview (mirrors baseRequest) instead of a server-side auto-pick.
            const resp = await cl2kMakerAPI.generateSeasons({
                tmdb_id: item.tmdb_id,
                title: item.title,
                seasons: nums,
                year: item.year,
                tvdb_id: item.tvdb_id,
                imdb_id: item.imdb_id,
                backdrop_path: customBackdrop ? null : backdrop,
                backdrop_b64: customBackdrop?.b64 || null,
                logo_path: logo,
                logo_b64: customLogo?.b64 || null,
                whiten: whitenLogo,
                invert: invertLogo,
                fit_mode: fitMode,
                focus_x: focusX,
                focus_y: focusY,
                crop_x: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.x : null,
                crop_y: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.y : null,
                crop_w: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.w : null,
                crop_h: (fitMode === 'fit' || fitMode === 'extend') && crop ? crop.h : null,
                v_pos: vPos,
                zoom: zoom,
                logo_scale: logoScale,
                logo_y_offset: logoYOffset,
                save_local: saveTargets.saveLocal,
                upload_gdrive: saveTargets.uploadGdrive,
                // Deliberate manual action — overwrite existing season posters too.
                force: true,
            });
            const jobId = resp?.data?.job_id;
            if (!jobId) throw new Error(resp?.message || 'Could not start season batch');

            // The batch runs server-side (it outlasts a request timeout) — poll its
            // progress instead of blocking on one long request. Tolerate transient
            // poll errors, but bail after a run of them (job evicted / server gone)
            // so the button never sticks in a spinner forever.
            let fails = 0;
            while (true) {
                await new Promise(r => setTimeout(r, 1500));
                let d;
                try {
                    d = (await cl2kMakerAPI.seasonsStatus(jobId))?.data;
                } catch {
                    if (++fails >= 10) throw new Error('Lost contact with the season job');
                    continue;
                }
                if (!d) {
                    if (++fails >= 10) throw new Error('Lost contact with the season job');
                    continue;
                }
                fails = 0;
                setBulkProgress(`${d.done}/${d.total}`);
                if (d.status === 'done' || d.status === 'error') {
                    if (d.status === 'error') {
                        toast.error(d.error || 'Season generation failed');
                    } else {
                        toast.success(`Seasons: ${d.generated}/${d.total} generated`);
                    }
                    break;
                }
            }
        } catch (err) {
            toast.error(err.message || 'Season generation failed');
        } finally {
            setBusy(false);
            setBulkProgress('');
        }
    }, [
        bulkSeasons,
        item,
        backdrop,
        customBackdrop,
        logo,
        customLogo,
        whitenLogo,
        invertLogo,
        saveTargets,
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

    // Per-source art map for the per-picker SourceSelector (Poster page picks
    // backdrop + logo sources independently from this).
    const artBySource = useMemo(
        () => ({ tmdb: tmdbArt, fanart: fanartArt, plex: plexArt }),
        [tmdbArt, fanartArt, plexArt]
    );
    const isRenderTab = tab === 'poster';

    return (
        <>
            {/* Selected title bar */}
            <section className="mt-6 px-4 py-3 bg-surface border border-border rounded-[12px]">
                <div className="flex items-center justify-between gap-3">
                    <div className="flex items-baseline gap-2.5 flex-wrap min-w-0">
                        <span className="font-display text-lg font-semibold text-fg truncate">
                            {item.title || `TMDB #${item.tmdb_id}`}
                        </span>
                        {item.year ? (
                            <span className="font-mono text-sm text-fg-subtle">{item.year}</span>
                        ) : null}
                        <span className="font-mono text-[10px] uppercase px-1.5 py-0.5 rounded bg-success/15 text-success">
                            {item.kind}
                        </span>
                        {item.tmdb_id ? (
                            <span className="font-mono text-[11px] px-2 py-0.5 rounded bg-surface-inset text-accent">
                                TMDB {item.tmdb_id}
                            </span>
                        ) : null}
                        {item.tvdb_id ? (
                            <span className="font-mono text-[11px] px-2 py-0.5 rounded bg-surface-inset text-accent">
                                TVDB {item.tvdb_id}
                            </span>
                        ) : null}
                        {item.imdb_id ? (
                            <span className="font-mono text-[11px] px-2 py-0.5 rounded bg-surface-inset text-accent">
                                {item.imdb_id}
                            </span>
                        ) : null}
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

            {/* Stage 2: build-type tabs (what you're making) + a More ▾ menu for
                the occasional finished-poster / edit workflows. Sources are picked
                per-picker inside each page. */}
            <div className="mt-6 flex flex-wrap items-center gap-3.5">
                <div className="flex gap-1 p-1 rounded-lg bg-surface-inset border border-border max-w-full overflow-x-auto">
                    {BUILD_TABS.map(t => {
                        const on = tab === t.key;
                        return (
                            <button
                                key={t.key}
                                type="button"
                                onClick={() => setTab(t.key)}
                                className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap px-3 sm:px-4 py-2 rounded-md text-[13px] transition-colors ${
                                    on
                                        ? 'bg-primary text-white font-semibold'
                                        : 'text-fg-muted hover:text-fg'
                                }`}
                            >
                                <span className="font-mono text-[9px] opacity-80">{t.ar}</span>
                                {t.label}
                            </button>
                        );
                    })}
                </div>
            </div>

            {/* Stage 3 + 4 panels */}
            {isRenderTab && (
                <RenderPanel
                    artBySource={artBySource}
                    seasonArt={isSeasonPoster ? seasonArt : null}
                    loadingArt={loadingArt}
                    backdrop={backdrop}
                    setBackdrop={setBackdropExclusive}
                    customBackdrop={customBackdrop}
                    setCustomBackdrop={setCustomBackdropExclusive}
                    backdropSource={backdropSource}
                    setBackdropSource={setBackdropSource}
                    logoSource={logoSource}
                    setLogoSource={setLogoSource}
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
                    invertLogo={invertLogo}
                    setInvertLogo={setInvertLogo}
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
                    setBandLabel={onBandLabel}
                    isSeasonPoster={isSeasonPoster}
                    bulkSeasons={bulkSeasons}
                    setBulkSeasons={setBulkSeasons}
                    onBulkSeasons={runBulkSeasons}
                    bulkProgress={bulkProgress}
                    removeText={removeText}
                    setRemoveText={setRemoveText}
                    brushSize={brushSize}
                    setBrushSize={setBrushSize}
                    maskB64={maskB64}
                    onMaskChange={setMaskB64}
                    previewUrl={previewUrl}
                    previewing={previewing}
                    onPreview={runPreview}
                    onGenerate={runGenerate}
                    onPsdExport={runPsdExport}
                    busy={busy}
                    saveTargets={saveTargets}
                    effectiveKind={effectiveKind}
                    toast={toast}
                />
            )}

            {tab === 'square' && (
                <SquareArtPanel
                    item={item}
                    artBySource={artBySource}
                    loadingArt={loadingArt}
                    saveTargets={saveTargets}
                    toast={toast}
                />
            )}
            {tab === 'background' && (
                <BackgroundArtPanel
                    item={item}
                    artBySource={artBySource}
                    loadingArt={loadingArt}
                    saveTargets={saveTargets}
                    toast={toast}
                />
            )}
            {tab === 'logo' && (
                <LogoAssetPanel
                    item={item}
                    artBySource={artBySource}
                    loadingArt={loadingArt}
                    saveTargets={saveTargets}
                    toast={toast}
                />
            )}

            {/* Each tab now renders its own "Recently generated" accordion in its
                right column, so no Builder-level history section is needed. */}
        </>
    );
};

// ─── Render panel (TMDB / fanart) ──────────────────────────────────────────

// Collapsible accordion for the studio's right-column secondary panels (AI text
// removal, touch-up, extraction, bulk seasons, history). Pure UI open/closed
// state — content (and all its handlers) is passed as children. `dot` shows a
// small accent indicator on the header when a flag is active.
// Optionally controlled: pass `open` + `onToggle` to drive the open state from
// the parent (e.g. so a success handler can collapse it); otherwise it manages
// its own UI-only state.
const StudioAccordion = ({
    title,
    count,
    dot = false,
    defaultOpen = false,
    open: openProp,
    onToggle,
    children,
}) => {
    const [openState, setOpenState] = useState(defaultOpen);
    const controlled = openProp !== undefined;
    const open = controlled ? openProp : openState;
    const toggle = () => (controlled ? onToggle?.() : setOpenState(o => !o));
    return (
        <div>
            <div className="h-px bg-border" />
            <button
                type="button"
                onClick={toggle}
                className="flex w-full items-center gap-2.5 px-2 -mx-2 py-2 rounded-md hover:bg-row-hover transition-colors"
            >
                <span
                    className={`material-symbols-outlined text-base text-fg-subtle transition-transform ${
                        open ? 'rotate-90' : ''
                    }`}
                >
                    chevron_right
                </span>
                <span className="flex-1 text-left font-mono text-[10px] tracking-wide uppercase text-fg-subtle">
                    {title}
                </span>
                {dot && <span className="w-1.5 h-1.5 rounded-full bg-accent" />}
                {count != null && (
                    <span className="font-mono text-[10px] text-fg-dim">{count}</span>
                )}
            </button>
            {open && <div className="pt-3">{children}</div>}
        </div>
    );
};

// A labelled section header for the always-visible studio control groups.
const StudioGroupLabel = ({ children }) => (
    <span className="font-mono text-[10px] tracking-wide uppercase text-fg-subtle">{children}</span>
);

const RenderPanel = ({
    artBySource,
    seasonArt,
    loadingArt,
    backdrop,
    setBackdrop,
    customBackdrop,
    setCustomBackdrop,
    backdropSource,
    setBackdropSource,
    logoSource,
    setLogoSource,
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
    invertLogo,
    setInvertLogo,
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
    bulkProgress,
    removeText,
    setRemoveText,
    brushSize,
    setBrushSize,
    maskB64,
    onMaskChange,
    previewUrl,
    previewing,
    onPreview,
    onGenerate,
    onPsdExport,
    busy,
    saveTargets,
    effectiveKind,
    toast,
}) => {
    // Independent per-picker sources (Option A): the backdrop and the logo each
    // choose their own source, so e.g. a Plex backdrop + a fanart.tv logo works.
    // State lives in the Builder (persisted with the session); switching a picker
    // OFF Upload clears its custom image — one consistent rule everywhere, no
    // invisible "the upload is still what renders" state.
    // 'upload' AND 'gdrive' both seed customBackdrop, so only clear it when
    // switching to a picker-grid source (tmdb/fanart/plex).
    const onBdSource = s => {
        setBackdropSource(s);
        if (s !== 'upload' && s !== 'gdrive') setCustomBackdrop(null);
    };
    const onLogoSource = s => {
        setLogoSource(s);
        if (s !== 'upload') setCustomLogo(null);
    };

    // Output mode: 'cl2k' = the full CL2K render (gradient + logo + framing +
    // season + border). 'asis' = file a poster built outside CHUB unchanged (just
    // the optional border, no logo/gradient/reframe) — the old "Finished poster"
    // tab, folded in so the Upload/GDrive sources feed it.
    const [outputMode, setOutputMode] = useState('cl2k'); // 'cl2k' | 'asis'
    const isAsis = outputMode === 'asis';
    const bdArt = artBySource[backdropSource] || null;
    const lgArt = artBySource[logoSource] || null;
    const backdrops = bdArt?.backdrops || [];
    const posters = bdArt?.posters || [];
    // Wordmark-first so real title logos beat TMDB's character-art junk.
    const logos = useMemo(() => sortWordmarkFirst(lgArt?.logos || []), [lgArt]);
    const seasonPosters = seasonArt?.posters || [];
    const backdropUrl = customBackdrop?.url || (backdrop ? urlForPath(backdrop) : null);
    // A render input exists — either a picker path or a custom upload. Gates the
    // preview/Generate actions (PSD stays path-only: the backend PSD route can't
    // take uploaded bytes and would silently swap in an auto-picked backdrop).
    const hasBackdrop = !!(backdrop || customBackdrop);
    // Template guide lines over the rendered preview (the PSD's cyan guides).
    const [showGuides, setShowGuides] = useState(true);

    const onBackdropFile = e => {
        const f = e.target.files?.[0];
        e.target.value = '';
        if (!f) return;
        const reader = new FileReader();
        reader.onload = () => {
            const url = String(reader.result);
            setCustomBackdrop({ b64: url.split(',').pop(), url, name: f.name });
        };
        reader.readAsDataURL(f);
    };

    // GDrive grab: pull a synced poster at FULL resolution (the raw cached file,
    // never the thumbnail) and seed it as the custom backdrop — same shape the
    // Upload source produces, so the render path downstream is identical.
    const [importing, setImporting] = useState(false);
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
                const url = String(dataUrl);
                setCustomBackdrop({ b64: url.split(',').pop(), url, name: poster.file });
            } catch (err) {
                toast.error(err.message || 'Import failed');
            } finally {
                setImporting(false);
            }
        },
        [setCustomBackdrop, toast]
    );

    // Synced posters that match the current title — auto-populated like the
    // TMDB/fanart/Plex grids (no manual search). Fetched lazily the first time the
    // GDrive source is shown, and again whenever the title changes.
    const [gdrivePosters, setGdrivePosters] = useState(null);
    const [gdriveLoading, setGdriveLoading] = useState(false);
    const [gdriveFor, setGdriveFor] = useState(null);
    useEffect(() => {
        if (backdropSource !== 'gdrive' || gdriveFor === item.title) return undefined;
        let cancelled = false;
        (async () => {
            setGdriveLoading(true);
            try {
                const resp = await postersAPI.browsePosters({
                    query: item.title || undefined,
                    image_type: 'poster',
                    limit: 60,
                });
                if (!cancelled) {
                    setGdrivePosters(resp?.data?.items || []);
                    setGdriveFor(item.title);
                }
            } catch (err) {
                if (!cancelled) {
                    setGdrivePosters([]);
                    setGdriveFor(item.title);
                    toast.error(err.message || 'GDrive browse failed');
                }
            } finally {
                if (!cancelled) setGdriveLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [backdropSource, gdriveFor, item.title, toast]);

    const bdSel = (
        <SourceSelector value={backdropSource} onChange={onBdSource} sources={BACKDROP_SOURCES} />
    );
    const plexBackdropEmpty =
        backdropSource === 'plex' && bdArt?.reason && !backdrops.length && !posters.length;
    const bdLabel = isAsis ? 'Poster image' : 'Backdrop';

    // ── File-as-is (finished poster) output ────────────────────────────────────
    // File-as-is: take a finished poster (Upload or GDrive grab) and file it with
    // minimal changes — optionally erase the old title (the Send to AI button bakes
    // the cleaned art into the backdrop) and draw a new title — via /retext. At save
    // apply_ai=false, so drawing the label costs no AI. No logo, gradient, or
    // reframe; just the new label + optional CL2K border.
    const [asisBorder, setAsisBorder] = useState(true);
    const [asisLabel, setAsisLabel] = useState(''); // new title drawn on the poster
    const [asisTextY, setAsisTextY] = useState(0.96); // vertical position (CL2K band = 96%)
    const [asisPreview, setAsisPreview] = useState(null); // { b64, sig }
    const [asisPreviewing, setAsisPreviewing] = useState(false);
    const [asisSaving, setAsisSaving] = useState(false);
    // File-as-is "Generate seasons" batch — local busy + "n/total" readout (the
    // full-CL2K batch's busy/bulkProgress are parent props for a different flow).
    const [asisBulkBusy, setAsisBulkBusy] = useState(false);
    const [asisBulkProgress, setAsisBulkProgress] = useState('');

    // The source poster as a data URL — /retext decodes it and draws the new label.
    const asisDataUrlFromSource = useCallback(async () => {
        if (!backdropUrl) return null;
        const blob = await (await fetch(backdropUrl)).blob();
        return new Promise((resolve, reject) => {
            const fr = new FileReader();
            fr.onload = () => resolve(fr.result);
            fr.onerror = reject;
            fr.readAsDataURL(blob);
        });
    }, [backdropUrl]);

    // Send to AI — erase the masked text from the backdrop via the configured
    // inpainter, then adopt the cleaned image as the (custom) backdrop so the
    // preview re-renders with the text gone. The brush mask is dropped (the text
    // is erased, and swapping the image clears the canvas), so a later Generate
    // does NOT re-run AI. This is the only paid step in the Full CL2K flow.
    const aiProvider = config?.ai_provider || 'none';
    const [aiErasing, setAiErasing] = useState(false);
    // Prompt defaults to the module-settings ai_prompt, editable per-erase.
    // Derived (not seeded via an effect) so it tracks config until the user types
    // — null means "untouched, show the default"; '' means they cleared it.
    const [aiPromptEdit, setAiPrompt] = useState(null);
    const aiPrompt = aiPromptEdit ?? (config?.ai_prompt || '');
    const runBackdropErase = useCallback(async () => {
        if (!backdropUrl || !maskB64 || aiProvider === 'none') return;
        setAiErasing(true);
        try {
            // Custom uploads are sent as bytes (we already hold the b64); a remote
            // CDN backdrop is sent as a path for the backend to fetch — the browser
            // can't fetch image.tmdb.org directly (no CORS header).
            const source = customBackdrop?.b64
                ? { image_b64: customBackdrop.b64 }
                : { image_path: backdrop };
            const resp = await cl2kMakerAPI.retext({
                ...source,
                mask_b64: maskB64,
                apply_ai: true,
                prompt: aiPrompt || config?.ai_prompt || '',
                label_text: '',
                border: false,
                preview: true,
                keep_size: true,
                kind: isSeasonPoster ? 'season' : effectiveKind,
                season_number: isSeasonPoster ? Number(seasonNumber) : null,
                title: item.title,
                tmdb_id: item.tmdb_id,
                year: item.year,
                tvdb_id: item.tvdb_id,
                imdb_id: item.imdb_id,
            });
            const erased = resp?.data?.preview_b64;
            if (erased) {
                setCustomBackdrop({
                    b64: erased,
                    url: `data:image/jpeg;base64,${erased}`,
                    name: customBackdrop?.name || 'erased.jpg',
                });
                onMaskChange(null);
                toast.success('Text erased — check the preview, then Generate & save.');
            } else {
                toast.error('AI returned no image');
            }
        } catch (err) {
            toast.error(err.message || 'AI erase failed');
        } finally {
            setAiErasing(false);
        }
    }, [
        backdropUrl,
        backdrop,
        maskB64,
        aiProvider,
        aiPrompt,
        config,
        isSeasonPoster,
        seasonNumber,
        effectiveKind,
        item,
        customBackdrop,
        setCustomBackdrop,
        onMaskChange,
        toast,
    ]);

    // Identity passed to /retext (filename + Plex match). Season info comes from
    // the Poster tab's own season controls, so there's no separate field here.
    const asisIds = useMemo(
        () => ({
            kind: isSeasonPoster ? 'season' : effectiveKind,
            season_number: isSeasonPoster ? Number(seasonNumber) : null,
            title: item.title,
            tmdb_id: item.tmdb_id,
            year: item.year,
            tvdb_id: item.tvdb_id,
            imdb_id: item.imdb_id,
        }),
        [isSeasonPoster, seasonNumber, effectiveKind, item]
    );

    // The EXPLICIT label override sent to /retext — a banner (e.g. COMPLETE LIMITED
    // SERIES) wins, else the free-text "New title" (only for non-season posters).
    // The SEASON N / Specials band is NOT spelled out here: the backend derives it
    // from season_number (season_band_text is the single source of truth), so an
    // empty label on a season poster tells it to draw the season band.
    const asisExplicitLabel = useMemo(
        () => bandLabel || (isSeasonPoster ? '' : asisLabel),
        [bandLabel, isSeasonPoster, asisLabel]
    );

    // Signature of the inputs that affect the as-is render. season_number is in here
    // because the backend derives the band from it, so changing the season must drop
    // the stale preview. A rendered preview is shown only while the sig still matches.
    const asisSig = useMemo(
        () =>
            JSON.stringify([
                backdropUrl,
                asisExplicitLabel,
                isSeasonPoster ? Number(seasonNumber) : null,
                asisTextY,
                asisBorder,
            ]),
        [backdropUrl, asisExplicitLabel, isSeasonPoster, seasonNumber, asisTextY, asisBorder]
    );

    // apply_ai=false: draws the (optional) new label + border on whatever the
    // backdrop currently is (the Send to AI button has already baked any erase in),
    // so this never spends AI credits.
    const runAsisPreview = useCallback(async () => {
        const image_b64 = await asisDataUrlFromSource();
        if (!image_b64) return;
        setAsisPreviewing(true);
        try {
            const resp = await cl2kMakerAPI.retext({
                image_b64,
                mask_b64: null,
                apply_ai: false,
                label_text: asisExplicitLabel,
                text_y: asisTextY,
                border: asisBorder,
                preview: true,
                ...asisIds,
            });
            setAsisPreview({ b64: resp?.data?.preview_b64 || null, sig: asisSig });
        } catch (err) {
            toast.error(err.message || 'Preview failed');
        } finally {
            setAsisPreviewing(false);
        }
    }, [asisDataUrlFromSource, asisExplicitLabel, asisTextY, asisBorder, asisIds, asisSig, toast]);

    const runAsisSave = useCallback(async () => {
        const image_b64 = await asisDataUrlFromSource();
        if (!image_b64) return;
        setAsisSaving(true);
        try {
            const resp = await cl2kMakerAPI.retext({
                image_b64,
                mask_b64: null,
                apply_ai: false,
                label_text: asisExplicitLabel,
                text_y: asisTextY,
                border: asisBorder,
                preview: false,
                ...asisIds,
                ...saveTargets.fields,
            });
            savedToast(toast, resp?.data);
        } catch (err) {
            toast.error(err.message || 'Save failed');
        } finally {
            setAsisSaving(false);
        }
    }, [
        asisDataUrlFromSource,
        asisExplicitLabel,
        asisTextY,
        asisBorder,
        asisIds,
        saveTargets.fields,
        toast,
    ]);

    // File-as-is "Generate seasons": re-file the one source poster once per season,
    // each with its own SEASON-N band (the backend derives the label). Runs in the
    // background and polls progress, mirroring the full-CL2K season batch.
    const runAsisBulkSeasons = useCallback(async () => {
        const nums = parseSeasonList(bulkSeasons);
        if (!nums.length) {
            toast.error('Enter season numbers, e.g. 1,2,3');
            return;
        }
        const image_b64 = await asisDataUrlFromSource();
        if (!image_b64) {
            toast.error('Upload or grab a poster first.');
            return;
        }
        setAsisBulkBusy(true);
        setAsisBulkProgress(`0/${nums.length}`);
        try {
            const resp = await cl2kMakerAPI.retextSeasons({
                image_b64,
                seasons: nums,
                title: item.title,
                tmdb_id: item.tmdb_id,
                year: item.year,
                tvdb_id: item.tvdb_id,
                imdb_id: item.imdb_id,
                text_y: asisTextY,
                border: asisBorder,
                ...saveTargets.fields,
            });
            const jobId = resp?.data?.job_id;
            if (!jobId) throw new Error(resp?.message || 'Could not start season batch');

            let fails = 0;
            while (true) {
                await new Promise(r => setTimeout(r, 1500));
                let d;
                try {
                    d = (await cl2kMakerAPI.seasonsStatus(jobId))?.data;
                } catch {
                    if (++fails >= 10) throw new Error('Lost contact with the season job');
                    continue;
                }
                if (!d) {
                    if (++fails >= 10) throw new Error('Lost contact with the season job');
                    continue;
                }
                fails = 0;
                setAsisBulkProgress(`${d.done}/${d.total}`);
                if (d.status === 'done' || d.status === 'error') {
                    if (d.status === 'error') {
                        toast.error(d.error || 'Season generation failed');
                    } else {
                        toast.success(`Seasons: ${d.generated}/${d.total} generated`);
                    }
                    break;
                }
            }
        } catch (err) {
            toast.error(err.message || 'Season generation failed');
        } finally {
            setAsisBulkBusy(false);
            setAsisBulkProgress('');
        }
    }, [
        bulkSeasons,
        asisDataUrlFromSource,
        item,
        asisTextY,
        asisBorder,
        saveTargets.fields,
        toast,
    ]);

    const asisFresh = !!(asisPreview?.b64 && asisPreview.sig === asisSig);
    const asisShownSrc = asisFresh ? `data:image/jpeg;base64,${asisPreview.b64}` : backdropUrl;

    // Latest as-is render inputs, read inside the debounced effect without making
    // its identity a trigger (the effect fires off asisSig). Mirrors baseRequestRef
    // for the full render.
    const asisPreviewInputsRef = useRef(null);
    useEffect(() => {
        asisPreviewInputsRef.current = {
            fromSource: asisDataUrlFromSource,
            label_text: asisExplicitLabel,
            text_y: asisTextY,
            border: asisBorder,
            ids: asisIds,
            sig: asisSig,
        };
    }, [asisDataUrlFromSource, asisExplicitLabel, asisTextY, asisBorder, asisIds, asisSig]);

    // Auto-render the as-is preview shortly after a label/position/border change
    // settles, so typing a New title (or setting a season/banner) shows on the
    // preview without a manual click — matching the full render's auto-preview.
    // apply_ai stays false (the Send to AI erase is a separate, paid step), so
    // this never spends AI credits.
    useEffect(() => {
        if (!isAsis || !hasBackdrop) return undefined;
        let cancelled = false;
        const handle = setTimeout(async () => {
            const p = asisPreviewInputsRef.current;
            const image_b64 = await p.fromSource();
            if (cancelled || !image_b64) return;
            setAsisPreviewing(true);
            try {
                const resp = await cl2kMakerAPI.retext({
                    image_b64,
                    mask_b64: null,
                    apply_ai: false,
                    label_text: p.label_text,
                    text_y: p.text_y,
                    border: p.border,
                    preview: true,
                    ...p.ids,
                });
                if (!cancelled)
                    setAsisPreview({ b64: resp?.data?.preview_b64 || null, sig: p.sig });
            } catch {
                /* auto-render stays quiet; the Preview button surfaces errors */
            } finally {
                if (!cancelled) setAsisPreviewing(false);
            }
        }, 300);
        return () => {
            cancelled = true;
            clearTimeout(handle);
        };
    }, [asisSig, isAsis, hasBackdrop]);

    const fileNameHint = `${item.title || `TMDB ${item.tmdb_id}`}${
        item.year ? ` (${item.year})` : ''
    }.jpg`;
    return (
        <section className="mt-4 flex flex-col gap-4">
            {/* Output mode — full CL2K render vs. file the image as-is. A second
                segmented pill tucked under the asset tabs, plus a filename hint. */}
            <div className="flex flex-wrap items-center gap-3.5">
                <div className="flex gap-1 p-1 rounded-lg bg-surface-inset border border-border">
                    <button
                        type="button"
                        onClick={() => setOutputMode('cl2k')}
                        className={`px-3.5 py-2 rounded-md text-[13px] transition-colors ${
                            outputMode === 'cl2k'
                                ? 'bg-primary text-white font-semibold'
                                : 'text-fg-muted hover:text-fg'
                        }`}
                    >
                        Full CL2K render
                    </button>
                    <button
                        type="button"
                        onClick={() => {
                            setOutputMode('asis');
                            // As-is files a manually-uploaded image only — drop any
                            // picker-path backdrop so a stale selection can't leak in.
                            setBackdropSource('upload');
                            setBackdrop(null);
                        }}
                        className={`px-3.5 py-2 rounded-md text-[13px] transition-colors ${
                            outputMode === 'asis'
                                ? 'bg-primary text-white font-semibold'
                                : 'text-fg-muted hover:text-fg'
                        }`}
                    >
                        File as-is
                    </button>
                </div>
                <span className="ml-auto font-mono text-[11px] text-fg-dim truncate">
                    → {fileNameHint}
                </span>
            </div>

            {isAsis ? (
                /* FILE-AS-IS single-column panel (mock cl2k-12). */
                <div className="grid grid-cols-1 md:grid-cols-[280px_minmax(0,1fr)] gap-6 items-start bg-surface border border-border rounded-[12px] p-5 max-w-[820px]">
                    <div className="flex flex-col gap-2">
                        <StudioGroupLabel>Preview</StudioGroupLabel>
                        <div className="relative aspect-[2/3] bg-black rounded-lg overflow-hidden flex items-center justify-center border border-border">
                            {hasBackdrop && asisShownSrc ? (
                                <img
                                    src={asisShownSrc}
                                    alt="Finished poster preview"
                                    className="w-full h-full object-contain"
                                />
                            ) : (
                                <span className="text-xs text-fg-subtle px-4 text-center">
                                    Upload a finished poster to start.
                                </span>
                            )}
                            <PreviewRefreshing active={asisPreviewing} />
                        </div>
                        <LoadingButton
                            onClick={runAsisPreview}
                            loading={asisPreviewing}
                            disabled={!hasBackdrop}
                            icon="visibility"
                            size="small"
                            variant="secondary"
                        >
                            Preview
                        </LoadingButton>
                    </div>
                    <div className="flex flex-col gap-4">
                        <div>
                            <h2 className="font-display text-base font-semibold text-fg">
                                Re-file an existing poster
                            </h2>
                            <p className="text-xs text-fg-subtle mt-1">
                                Upload a finished poster and save it under DAPS naming — no CL2K
                                render.
                            </p>
                        </div>
                        <UploadArtCard
                            label="Poster image"
                            custom={customBackdrop}
                            onFile={onBackdropFile}
                            onClear={() => setCustomBackdrop(null)}
                        />
                        {item.kind === 'show' && (
                            <label className="flex items-center gap-2 text-sm text-fg-muted">
                                <span className="w-28">Season number</span>
                                <input
                                    type="number"
                                    min="0"
                                    value={seasonNumber}
                                    onChange={e => setSeasonNumber(e.target.value)}
                                    placeholder="blank = none, 0 = Specials"
                                    className="flex-1 bg-surface border border-border rounded px-2 py-1 text-sm text-fg"
                                />
                            </label>
                        )}
                        {item.kind === 'show' && (
                            <div className="flex flex-col gap-1">
                                <div className="flex items-center gap-2">
                                    <span className="w-28 text-sm text-fg-muted">All seasons</span>
                                    <input
                                        type="text"
                                        value={bulkSeasons}
                                        onChange={e => setBulkSeasons(e.target.value)}
                                        placeholder="Generate all: 1,2,3"
                                        className="flex-1 bg-surface border border-border rounded px-2 py-1 text-sm text-fg"
                                    />
                                    <LoadingButton
                                        onClick={runAsisBulkSeasons}
                                        loading={asisBulkBusy}
                                        disabled={!hasBackdrop || saveTargets.noTarget}
                                        variant="secondary"
                                        icon="grid_view"
                                        size="small"
                                    >
                                        Generate seasons
                                    </LoadingButton>
                                    {asisBulkBusy && asisBulkProgress && (
                                        <span className="text-xs text-fg-muted tabular-nums whitespace-nowrap">
                                            {asisBulkProgress}
                                        </span>
                                    )}
                                </div>
                                <p className="text-xs text-fg-subtle">
                                    Files this poster once per season with its own SEASON N band
                                    (Season 0 = Specials). Runs in the background — the count
                                    updates as each season is saved.
                                </p>
                            </div>
                        )}
                        {item.kind !== 'collection' && (
                            <label className="flex items-center gap-2 text-sm text-fg-muted">
                                <span className="w-28">Banner</span>
                                <select
                                    value={bandLabel}
                                    onChange={e => setBandLabel(e.target.value)}
                                    className="flex-1 bg-surface border border-border rounded px-2 py-1 text-sm text-fg"
                                >
                                    {BAND_LABEL_OPTIONS.map(o => (
                                        <option key={o.value} value={o.value}>
                                            {o.label}
                                        </option>
                                    ))}
                                </select>
                            </label>
                        )}
                        <label className="flex flex-col gap-1 text-sm text-fg-muted">
                            <span>New title (fallback — used when no season or banner is set)</span>
                            <input
                                type="text"
                                value={asisLabel}
                                onChange={e => setAsisLabel(e.target.value)}
                                disabled={isSeasonPoster || !!bandLabel}
                                placeholder="leave blank to keep the poster as-is"
                                className="bg-surface border border-border rounded px-2 py-1 text-sm text-fg disabled:opacity-50"
                            />
                        </label>
                        <label className="flex items-center gap-2 text-sm text-fg-muted">
                            <span className="w-20">Position</span>
                            <input
                                type="range"
                                min="0"
                                max="100"
                                value={Math.round(asisTextY * 100)}
                                onChange={e => setAsisTextY(Number(e.target.value) / 100)}
                                className="flex-1"
                            />
                            <span className="w-10 text-right font-mono text-xs text-fg-subtle">
                                {Math.round(asisTextY * 100)}%
                            </span>
                        </label>
                        <p className="text-xs text-fg-subtle">
                            Drawn in the CL2K font at 96% — the locked CL2K band position (the
                            season/specials line). Set a Season number (draws SEASON N / SPECIALS);
                            a Banner overrides it (e.g. COMPLETE LIMITED SERIES). The New title box
                            is the fallback when neither is set. Brush over the old text and{' '}
                            <span className="text-fg-muted">Send to AI</span> first to remove it.
                        </p>
                        <div className="flex items-center justify-between gap-3">
                            <span className="text-sm text-fg font-medium">
                                Add CL2K white border
                            </span>
                            <Toggle
                                checked={asisBorder}
                                onChange={setAsisBorder}
                                label="Add CL2K white border"
                            />
                        </div>
                        <p className="text-xs text-fg-subtle">
                            The DAPS default 26px white frame (per the CL2K PSD). Uncheck only if
                            this poster already has the required border.
                        </p>
                        <SaveTargets targets={saveTargets} />
                        <LoadingButton
                            onClick={runAsisSave}
                            loading={asisSaving}
                            disabled={!hasBackdrop || saveTargets.noTarget}
                            icon="save"
                        >
                            Save as {fileNameHint}
                        </LoadingButton>
                        <p className="text-xs text-fg-subtle">
                            .psd export is unavailable for as-is files — the original is copied,
                            renamed, and optionally bordered.
                        </p>
                    </div>
                </div>
            ) : (
                /* FULL CL2K STUDIO — 3-column grid (mock cl2k-02). */
                <div className="grid grid-cols-1 xl:grid-cols-[320px_minmax(0,1fr)_300px] gap-4 items-start">
                    {/* LEFT: source pickers */}
                    <section className="bg-surface border border-border rounded-[12px] p-4 flex flex-col gap-[18px]">
                        {!isAsis && seasonPosters.length > 0 && (
                            <Picker
                                label="Season poster (tmdb)"
                                items={seasonPosters}
                                loading={false}
                                selected={backdrop}
                                onSelect={setBackdrop}
                                aspect="aspect-[2/3]"
                                emptyText="No TMDB season posters."
                            />
                        )}
                        {/* Source. As-is = a plain manual upload (no source selector).
                        Otherwise source-selectable: 'Upload' swaps the grid for a
                        custom-image dropzone; 'GDrive' for the sync-cache picker;
                        official posters from the same source appear below. */}
                        {isAsis ? (
                            <UploadArtCard
                                label="Poster image"
                                custom={customBackdrop}
                                onFile={onBackdropFile}
                                onClear={() => setCustomBackdrop(null)}
                            />
                        ) : backdropSource === 'upload' ? (
                            <UploadArtCard
                                label={bdLabel}
                                headerRight={bdSel}
                                custom={customBackdrop}
                                onFile={onBackdropFile}
                                onClear={() => setCustomBackdrop(null)}
                            />
                        ) : backdropSource === 'gdrive' ? (
                            <div className="bg-surface border border-border rounded-lg p-3">
                                <div className="flex items-center justify-between gap-2 mb-2">
                                    <h3 className="text-sm font-medium text-fg">{bdLabel}</h3>
                                    {bdSel}
                                </div>
                                {customBackdrop ? (
                                    <div className="flex items-center gap-3 rounded-md border-2 border-primary bg-surface-alt p-2">
                                        <img
                                            src={customBackdrop.url}
                                            alt="Grabbed"
                                            className="h-16 w-auto max-w-[60%] object-contain rounded"
                                        />
                                        <span className="flex-1 truncate text-xs text-fg-muted">
                                            {customBackdrop.name}
                                        </span>
                                        <Button
                                            onClick={() => setCustomBackdrop(null)}
                                            variant="secondary"
                                            icon="close"
                                            size="small"
                                        >
                                            Remove
                                        </Button>
                                    </div>
                                ) : gdriveLoading || gdrivePosters === null ? (
                                    <div className="text-xs text-fg-subtle py-4">Searching…</div>
                                ) : gdrivePosters.length === 0 ? (
                                    <div className="text-xs text-fg-subtle py-2">
                                        No synced posters match this title. Only images already
                                        pulled by Sync GDrive appear here.
                                    </div>
                                ) : (
                                    <div
                                        className="grid gap-2 max-h-72 overflow-auto"
                                        style={{
                                            gridTemplateColumns:
                                                'repeat(auto-fill, minmax(96px, 1fr))',
                                        }}
                                    >
                                        {gdrivePosters.map(p => (
                                            <button
                                                key={p.id || `${p.folder}/${p.file}`}
                                                type="button"
                                                disabled={importing}
                                                onClick={() => importFromSync(p)}
                                                title={p.file}
                                                className="relative bg-surface-alt overflow-hidden rounded border border-border hover:border-primary disabled:opacity-50 p-0"
                                                style={{ aspectRatio: '2 / 3' }}
                                            >
                                                <img
                                                    src={
                                                        p.id
                                                            ? postersAPI.getThumbnailUrl(p.id, 200)
                                                            : postersAPI.getPreviewUrl(
                                                                  p.folder,
                                                                  p.file
                                                              )
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
                                )}
                                {importing && (
                                    <div className="text-xs text-fg-subtle mt-2">
                                        Importing full-resolution poster…
                                    </div>
                                )}
                            </div>
                        ) : (
                            <>
                                <Picker
                                    label={bdLabel}
                                    headerRight={bdSel}
                                    items={backdrops}
                                    loading={loadingArt}
                                    selected={backdrop}
                                    onSelect={setBackdrop}
                                    aspect="aspect-video"
                                    emptyText={
                                        plexBackdropEmpty
                                            ? bdArt.reason
                                            : 'No backdrops from this source.'
                                    }
                                />
                                {posters.length > 0 && (
                                    <Picker
                                        label="Poster"
                                        items={posters}
                                        loading={loadingArt}
                                        selected={backdrop}
                                        onSelect={setBackdrop}
                                        aspect="aspect-[2/3]"
                                        emptyText="No posters from this source."
                                    />
                                )}
                            </>
                        )}

                        {/* Logo source picker (grid + source tabs only — controls live
                        in the right column). */}
                        <LogoSelector
                            variant="picker"
                            label="Logo"
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
                            invert={invertLogo}
                            onInvert={setInvertLogo}
                            touchUpUrl={logoTouchUpUrl}
                            onFlipMask={onLogoFlip}
                            source={logoSource}
                            onSource={onLogoSource}
                            emptyText={
                                logoSource === 'plex' && lgArt?.reason && !logos.length
                                    ? lgArt.reason
                                    : 'No logos from this source — switch source or Upload, or a text wordmark is used as fallback.'
                            }
                        />
                    </section>

                    {/* CENTER: large persistent preview + actions (never moves). The
                        crop framer lives in the right-column Framing group. */}
                    <section className="sticky top-0 self-start flex flex-col items-center gap-[13px]">
                        <div className="relative aspect-[2/3] h-[clamp(640px,80vh,880px)] max-w-full bg-black rounded-[10px] overflow-hidden flex items-center justify-center border border-border shadow-lg">
                            {hasBackdrop && previewUrl ? (
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
                                            kind={item.kind}
                                        />
                                    )}
                                    {showGuides && <GuideOverlay />}
                                    <PreviewRefreshing active={previewing} />
                                </>
                            ) : (
                                <span className="text-xs text-fg-subtle px-4 text-center">
                                    {!hasBackdrop
                                        ? 'Select a backdrop to start.'
                                        : previewing
                                          ? 'Rendering preview…'
                                          : 'Preview unavailable — tap Refresh.'}
                                </span>
                            )}
                        </div>

                        {/* Primary actions */}
                        <div className="flex gap-2 w-full max-w-[420px] flex-wrap">
                            <LoadingButton
                                onClick={onGenerate}
                                loading={busy}
                                disabled={!hasBackdrop || saveTargets.noTarget}
                                icon="save"
                                className="flex-1 min-w-[150px]"
                            >
                                Generate &amp; save
                            </LoadingButton>
                            <LoadingButton
                                onClick={onPreview}
                                loading={previewing}
                                disabled={!hasBackdrop}
                                icon="refresh"
                                variant="secondary"
                            >
                                Preview
                            </LoadingButton>
                            <LoadingButton
                                onClick={onPsdExport}
                                loading={busy}
                                disabled={!backdrop}
                                variant="secondary"
                                icon="layers"
                            >
                                .psd
                            </LoadingButton>
                        </div>

                        {backdropUrl && (
                            <div className="flex gap-2 w-full max-w-[420px]">
                                <a
                                    href={backdropUrl}
                                    download
                                    className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-xs border border-border text-fg-muted hover:border-primary"
                                    title="Download the backdrop to clean externally (Firefly/Photoshop), then re-import via the backdrop Upload source"
                                >
                                    <span className="material-symbols-outlined text-base">
                                        download
                                    </span>
                                    Download backdrop
                                </a>
                            </div>
                        )}

                        {/* Save targets + Generate handoff hint */}
                        <div className="w-full max-w-[420px] flex flex-col gap-2">
                            <SaveTargets targets={saveTargets} />
                            <p className="text-xs text-fg-subtle">
                                Handoff: download the backdrop, clean it in Firefly/Photoshop, then
                                bring it back via the backdrop{' '}
                                <span className="text-fg-muted">Upload</span> source.
                            </p>
                        </div>
                    </section>

                    {/* RIGHT: framing + logo controls + accordions */}
                    <section className="bg-surface border border-border rounded-[12px] p-4 flex flex-col gap-3.5">
                        {/* FRAMING — always visible (Zoom / Vertical / Focus Y +
                            guides). The sliders only call setZoom/setVPos/onFocusChange
                            — all RenderPanel props — so no CropFramer drag math moves. */}
                        <div className="flex flex-col gap-3">
                            <StudioGroupLabel>Framing</StudioGroupLabel>
                            {backdropUrl && (
                                <CropFramer
                                    compact
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
                                            ? bandLabel ||
                                              (Number(seasonNumber) === 0
                                                  ? 'Specials'
                                                  : `Season ${seasonNumber}`)
                                            : bandLabel ||
                                              (item.kind === 'collection' ? 'COLLECTION' : '')
                                    }
                                    labelYFrac={
                                        !isSeasonPoster && !bandLabel && item.kind === 'collection'
                                            ? 1350 / 1500
                                            : 1440 / 1500
                                    }
                                />
                            )}
                            <div>
                                <div className="flex justify-between mb-1.5">
                                    <span className="text-sm text-fg-muted">Zoom</span>
                                    <span className="font-mono text-xs text-fg-subtle">
                                        {(zoom ?? 1).toFixed(2)}×
                                    </span>
                                </div>
                                <input
                                    type="range"
                                    min="0.5"
                                    max="3"
                                    step="0.05"
                                    value={zoom ?? 1}
                                    onChange={e => setZoom(Number(e.target.value))}
                                    className="w-full"
                                />
                            </div>
                            <div>
                                <div className="flex justify-between mb-1.5">
                                    <span className="text-sm text-fg-muted">Vertical position</span>
                                    <span className="font-mono text-xs text-fg-subtle">
                                        {Math.round((vPos ?? 0) * 100)}
                                    </span>
                                </div>
                                <input
                                    type="range"
                                    min="0"
                                    max="1"
                                    step="0.01"
                                    value={vPos}
                                    onChange={e => setVPos(Number(e.target.value))}
                                    className="w-full"
                                />
                            </div>
                            <div>
                                <div className="flex justify-between mb-1.5">
                                    <span className="text-sm text-fg-muted">Focus Y</span>
                                    <span className="font-mono text-xs text-fg-subtle">
                                        {(focusY ?? 0.5).toFixed(2)}
                                    </span>
                                </div>
                                <input
                                    type="range"
                                    min="0"
                                    max="1"
                                    step="0.01"
                                    value={focusY ?? 0.5}
                                    onChange={e => onFocusChange(focusX, Number(e.target.value))}
                                    className="w-full"
                                />
                            </div>
                            <div className="flex items-center justify-between">
                                <span className="text-sm text-fg-muted">CL2K guides</span>
                                <GuidesToggle show={showGuides} onChange={setShowGuides} />
                            </div>
                        </div>

                        {/* LOGO controls — always visible (colour mode + sliders +
                            invert). Touch-up brush lives in its own accordion below. */}
                        <div className="h-px bg-border" />
                        <div className="flex flex-col gap-3">
                            <StudioGroupLabel>Logo</StudioGroupLabel>
                            <LogoSelector
                                variant="controls"
                                label="Logo"
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
                                invert={invertLogo}
                                onInvert={setInvertLogo}
                                touchUpUrl={logoTouchUpUrl}
                                onFlipMask={onLogoFlip}
                                source={logoSource}
                                onSource={onLogoSource}
                            />
                        </div>

                        {/* SEASON · BANNER — season-number always visible; bulk in an
                            accordion below. Banner select for non-collections. */}
                        {(item.kind === 'show' || item.kind !== 'collection') && (
                            <>
                                <div className="h-px bg-border" />
                                <div className="flex flex-col gap-3">
                                    <StudioGroupLabel>Season · Banner</StudioGroupLabel>
                                    {item.kind === 'show' && (
                                        <SeasonControls
                                            variant="season"
                                            seasonNumber={seasonNumber}
                                            setSeasonNumber={setSeasonNumber}
                                            bulkSeasons={bulkSeasons}
                                            setBulkSeasons={setBulkSeasons}
                                            onBulkSeasons={onBulkSeasons}
                                            bulkProgress={bulkProgress}
                                            busy={busy}
                                        />
                                    )}
                                    {item.kind !== 'collection' && (
                                        <div>
                                            <label className="flex items-center gap-2 text-sm text-fg-muted">
                                                <span className="w-28 text-fg font-medium">
                                                    Banner
                                                </span>
                                                <select
                                                    value={bandLabel}
                                                    onChange={e => setBandLabel(e.target.value)}
                                                    className="flex-1 bg-surface border border-border rounded px-2 py-1 text-sm text-fg"
                                                >
                                                    {BAND_LABEL_OPTIONS.map(o => (
                                                        <option key={o.value} value={o.value}>
                                                            {o.label}
                                                        </option>
                                                    ))}
                                                </select>
                                            </label>
                                            <p className="text-xs text-fg-subtle mt-2">
                                                Optional bottom banner in the CL2K label band (e.g.
                                                a limited series). On a season poster it replaces
                                                the SEASON N text — the file is still saved as the
                                                season poster.
                                            </p>
                                        </div>
                                    )}
                                </div>
                            </>
                        )}

                        {/* ACCORDION: AI text removal */}
                        <StudioAccordion title="AI text removal" dot={removeText}>
                            <AiPanel
                                config={config}
                                removeText={removeText}
                                setRemoveText={setRemoveText}
                                brushSize={brushSize}
                                setBrushSize={setBrushSize}
                                backdropUrl={backdropUrl}
                                mask={maskB64}
                                onMaskChange={onMaskChange}
                                hasMask={!!maskB64}
                                aiBusy={aiErasing}
                                onSendToAi={runBackdropErase}
                                aiPrompt={aiPrompt}
                                setAiPrompt={setAiPrompt}
                            />
                        </StudioAccordion>

                        {/* ACCORDION: Logo touch-up (B/W brush over the processed logo) */}
                        {logoTouchUpUrl && whitenLogo && (
                            <StudioAccordion title="Logo touch-up">
                                <LogoSelector
                                    variant="touchup"
                                    label="Logo"
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
                                    invert={invertLogo}
                                    onInvert={setInvertLogo}
                                    touchUpUrl={logoTouchUpUrl}
                                    onFlipMask={onLogoFlip}
                                    source={logoSource}
                                    onSource={onLogoSource}
                                />
                            </StudioAccordion>
                        )}

                        {/* ACCORDION: Bulk seasons (shows only) */}
                        {item.kind === 'show' && (
                            <StudioAccordion title="Bulk seasons">
                                <SeasonControls
                                    variant="bulk"
                                    seasonNumber={seasonNumber}
                                    setSeasonNumber={setSeasonNumber}
                                    bulkSeasons={bulkSeasons}
                                    setBulkSeasons={setBulkSeasons}
                                    onBulkSeasons={onBulkSeasons}
                                    bulkProgress={bulkProgress}
                                    busy={busy}
                                />
                            </StudioAccordion>
                        )}

                        {/* ACCORDION: Recently generated (moved from Builder level) */}
                        <StudioAccordion title="Recently generated">
                            <HistorySection toast={toast} />
                        </StudioAccordion>
                    </section>
                </div>
            )}
        </section>
    );
};

// Presentational split for the studio right column: 'season' = the single
// Season-number input (always visible under SEASON·BANNER); 'bulk' = the
// "1,2,3 → Generate seasons" row + help (a collapsed accordion); undefined =
// the whole card. No handler logic differs by variant — props still flow.
const SeasonControls = ({
    seasonNumber,
    setSeasonNumber,
    bulkSeasons,
    setBulkSeasons,
    onBulkSeasons,
    bulkProgress,
    busy,
    variant,
}) => {
    const showSeason = variant !== 'bulk';
    const showBulk = variant !== 'season';
    const cardCls = variant
        ? 'flex flex-col gap-3'
        : 'bg-surface border border-border rounded-lg p-3 flex flex-col gap-3';
    return (
        <div className={cardCls}>
            {!variant && <h3 className="text-sm font-medium text-fg">Season variant</h3>}
            {showSeason && (
                <label className="flex items-center gap-2 text-sm text-fg-muted">
                    <span className="w-28">Season number</span>
                    <input
                        type="number"
                        min="0"
                        value={seasonNumber}
                        onChange={e => setSeasonNumber(e.target.value)}
                        placeholder="blank = show poster, 0 = Specials"
                        className="flex-1 bg-surface border border-border rounded px-2 py-1 text-sm text-fg"
                    />
                </label>
            )}
            {showBulk && (
                <>
                    <div className="flex items-center gap-2">
                        <input
                            type="text"
                            value={bulkSeasons}
                            onChange={e => setBulkSeasons(e.target.value)}
                            placeholder="Generate all: 1,2,3"
                            className="flex-1 bg-surface border border-border rounded px-2 py-1 text-sm text-fg"
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
                        {busy && bulkProgress && (
                            <span className="text-xs text-fg-muted tabular-nums whitespace-nowrap">
                                {bulkProgress}
                            </span>
                        )}
                    </div>
                    <p className="text-xs text-fg-subtle">
                        Each season reuses the backdrop &amp; logo from the poster you built above;
                        only the season number changes. Runs in the background — the count updates
                        as each season is saved.
                    </p>
                </>
            )}
        </div>
    );
};

// ─── AI text-removal panel + brush canvas ──────────────────────────────────

const AiPanel = ({
    config,
    removeText,
    setRemoveText,
    brushSize,
    setBrushSize,
    backdropUrl,
    mask,
    onMaskChange,
    hasMask,
    aiBusy,
    onSendToAi,
    aiPrompt,
    setAiPrompt,
}) => {
    // UI-only: the large pop-out mask editor (mock cl2k-09). Reuses the same
    // BrushMask + onMaskChange pipeline — no new mask handlers. Both the inline
    // and pop-out canvases seed from the current `mask`, and the inline one is
    // keyed on modalOpen so it remounts (and re-seeds from the updated mask) when
    // the pop-out closes — strokes carry both ways.
    const [modalOpen, setModalOpen] = useState(false);
    const provider = config?.ai_provider || 'none';
    // Why AI can't run (mirrors the backend's unavailable_reason) — gates the
    // Send to AI button so it doesn't silently no-op. api_key reads back as
    // '********' when set (redacted) and '' when unset.
    const aiBlock =
        provider === 'none'
            ? 'AI provider is “none” — enable one in Module Settings or this has no effect.'
            : (provider === 'openai' || provider === 'huggingface') && !config?.api_key
              ? 'No API key set for this provider — add one in Module Settings.'
              : provider === 'lama_sidecar' && !config?.ai_endpoint
                ? 'No AI Endpoint set — add your LaMa container URL in Module Settings.'
                : null;
    return (
        <>
            <div className="bg-surface border border-border rounded-lg p-3 flex flex-col gap-3">
                <label className="flex items-center gap-2 text-sm text-fg font-medium">
                    <input
                        type="checkbox"
                        checked={removeText}
                        onChange={e => setRemoveText(e.target.checked)}
                    />
                    Remove text with AI
                </label>
                <p className="text-xs text-fg-subtle">
                    Provider: <span className="text-fg-muted">{provider}</span>. OpenAI re-imagines
                    the whole image — brush a mask over just the text to keep faces/art intact. Set
                    the provider/key in{' '}
                    <Link
                        to="/settings/modules/cl2k_maker"
                        className="text-fg underline hover:no-underline"
                    >
                        Module Settings
                    </Link>
                    .
                </p>
                {removeText && aiBlock && <div className="text-xs text-warning">{aiBlock}</div>}
                {removeText && (
                    <>
                        <label className="flex items-center gap-2 text-sm text-fg-muted">
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
                                key={modalOpen ? 'inline-modal-open' : 'inline-modal-closed'}
                                imageUrl={backdropUrl}
                                brushSize={brushSize}
                                onMaskChange={onMaskChange}
                                initialMask={mask}
                            />
                        ) : (
                            <div className="text-xs text-fg-subtle">
                                Select a backdrop to brush a mask over.
                            </div>
                        )}
                        {backdropUrl && (
                            <button
                                type="button"
                                onClick={() => setModalOpen(true)}
                                className="self-start inline-flex items-center gap-1.5 h-[30px] px-[11px] rounded-[7px] text-xs font-semibold border border-border bg-surface-elevated text-fg-muted transition-colors hover:border-border-light"
                            >
                                <span className="material-symbols-outlined text-[15px]">
                                    open_in_full
                                </span>
                                Open large editor
                            </button>
                        )}
                        {backdropUrl && (
                            <>
                                <label className="flex flex-col gap-1 text-sm text-fg-muted">
                                    <span>AI prompt (defaults to module settings)</span>
                                    <textarea
                                        value={aiPrompt}
                                        onChange={e => setAiPrompt(e.target.value)}
                                        rows={2}
                                        className="bg-surface border border-border rounded px-2 py-1 text-sm text-fg"
                                    />
                                </label>
                                <LoadingButton
                                    onClick={onSendToAi}
                                    loading={aiBusy}
                                    disabled={!hasMask || !!aiBlock}
                                    icon="auto_fix_high"
                                >
                                    Send to AI — erase masked text
                                </LoadingButton>
                                <p className="text-xs text-fg-subtle">
                                    Erases the brushed text and updates the preview, so you see the
                                    result before you Generate &amp; save. This is the only step
                                    that uses AI credits.
                                </p>
                            </>
                        )}
                    </>
                )}
            </div>
            {/* Large pop-out mask editor (mock cl2k-09). Reuses the same BrushMask +
            onMaskChange pipeline at a bigger size — both canvases seed from the
            shared `mask`, so strokes carry between the inline brush and the pop-out. */}
            {modalOpen && backdropUrl && (
                <div
                    onClick={() => setModalOpen(false)}
                    className="fixed inset-0 z-modal flex items-center justify-center p-8 bg-black/80 backdrop-blur-sm"
                >
                    <div
                        onClick={e => e.stopPropagation()}
                        className="w-[min(1080px,94vw)] max-h-[90vh] bg-canvas border border-border rounded-[16px] shadow-2xl flex flex-col overflow-hidden"
                    >
                        <div className="flex items-center gap-3 px-5 py-4 border-b border-border">
                            <span className="font-display text-base font-semibold text-fg">
                                AI text removal
                            </span>
                            <span className="font-mono text-xs text-fg-subtle">
                                {provider} · inpaint
                            </span>
                            <button
                                type="button"
                                onClick={() => setModalOpen(false)}
                                className="ml-auto inline-flex items-center gap-1.5 h-[30px] px-[11px] rounded-[7px] text-xs font-semibold border border-border bg-surface-elevated text-fg-muted transition-colors hover:border-border-light"
                            >
                                <span className="material-symbols-outlined text-[15px]">close</span>
                                Close
                            </button>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_268px] min-h-0 flex-1">
                            <div className="flex items-center justify-center p-6 bg-black/40 min-h-[360px] overflow-auto">
                                <div className="max-w-full">
                                    <BrushMask
                                        imageUrl={backdropUrl}
                                        brushSize={brushSize}
                                        onMaskChange={onMaskChange}
                                        initialMask={mask}
                                    />
                                </div>
                            </div>
                            <div className="border-l border-border p-5 flex flex-col gap-4 overflow-y-auto">
                                <p className="text-xs leading-relaxed text-fg-muted">
                                    Brush over every title, logo and watermark you want gone. The
                                    masked region is sent to the AI inpainter with your prompt.
                                </p>
                                <label className="flex items-center gap-2 text-sm text-fg-muted">
                                    <span className="w-20">Brush size</span>
                                    <input
                                        type="range"
                                        min="4"
                                        max="80"
                                        value={brushSize}
                                        onChange={e => setBrushSize(Number(e.target.value))}
                                        className="flex-1"
                                    />
                                    <span className="w-10 text-right font-mono text-xs text-fg-subtle">
                                        {brushSize}px
                                    </span>
                                </label>
                                <label className="flex flex-col gap-1 text-sm text-fg-muted">
                                    <span>AI prompt</span>
                                    <textarea
                                        value={aiPrompt}
                                        onChange={e => setAiPrompt(e.target.value)}
                                        rows={3}
                                        className="bg-surface border border-border rounded px-2 py-1 text-sm text-fg"
                                    />
                                </label>
                                {aiBlock && <div className="text-xs text-warning">{aiBlock}</div>}
                                <div className="flex-1" />
                                <LoadingButton
                                    onClick={onSendToAi}
                                    loading={aiBusy}
                                    disabled={!hasMask || !!aiBlock}
                                    icon="auto_fix_high"
                                >
                                    Send to AI
                                </LoadingButton>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
};

/**
 * Brush a white-on-black mask over the backdrop. White = remove. The canvas
 * backing store holds opaque white strokes on a transparent background; CSS
 * opacity only dims the display, so toDataURL still yields a clean mask that the
 * backend resizes to the backdrop and feeds to the AI inpainter.
 */
const BrushMask = ({ imageUrl, brushSize, onMaskChange, initialMask = null }) => {
    const canvasRef = useRef(null);
    const drawing = useRef(false);

    // Size the canvas to the displayed image, then re-paint any existing mask onto
    // it so a freshly-mounted instance (e.g. the pop-out editor, or the inline one
    // after the pop-out closes) shows the strokes already made. drawImage scales
    // the prior mask to this canvas, so the inline ↔ pop-out size difference is
    // handled — and emit() captures the union when painting continues.
    const sizeToImage = useCallback(
        img => {
            const c = canvasRef.current;
            if (!c) return;
            c.width = img.clientWidth;
            c.height = img.clientHeight;
            if (initialMask) {
                const m = new Image();
                m.onload = () => {
                    const ctx = c.getContext('2d');
                    ctx.drawImage(m, 0, 0, c.width, c.height);
                };
                m.src = initialMask.startsWith('data:')
                    ? initialMask
                    : `data:image/png;base64,${initialMask}`;
            }
        },
        [initialMask]
    );

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
                <button
                    type="button"
                    onClick={clear}
                    className="inline-flex items-center self-start h-[30px] px-[11px] rounded-[7px] bg-surface-inset border border-border text-fg-muted text-xs font-semibold transition-colors hover:border-border-light"
                >
                    Clear mask
                </button>
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
// backend geometry (gradient 780→1375, logo bottom 1352, label 1440/1350 of 1500).
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
                {/* Logo zone (y=1100 → bottom-aligned at the y=1352 guide) */}
                <div
                    className="absolute pointer-events-none flex items-end justify-center"
                    style={{
                        left: '20%',
                        width: '60%',
                        top: '73.3%',
                        height: '16.8%',
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
            <p className="text-xs text-fg-subtle mt-1 text-center" style={{ width: 150 }}>
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
    // setVPos / setZoom are still passed by the parent (the Zoom + Vertical
    // sliders now live in the right-column FRAMING group), but CropFramer only
    // reads vPos/zoom for its canvas math — the slider UI moved out.
    zoom,
    focusX,
    focusY,
    onChange,
    mockLabel = '',
    labelYFrac = 1440 / 1500,
    // Compact = the right-rail placement: no nested card chrome, no FitMock
    // (the big center preview is the result view), image fills the rail width.
    compact = false,
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
        // Zoom scales the sampled region by 1/z about the cover crop's centre,
        // mirroring the backend's cover-fill zoom: >1 punches in (smaller
        // region), <1 samples beyond the cover crop so more of the source shows,
        // the freed bands falling into the CL2K gradient/border as black.
        const z = Math.max(CONTROL_RANGES.zoom.min, Math.min(zoom || 1, CONTROL_RANGES.zoom.max));
        const w = coverRect.w / z;
        const h0 = coverRect.h / z;
        const x = coverRect.left + (coverRect.w - w) / 2;
        const y0 = coverRect.top + (coverRect.h - h0) / 2;
        // vPos then pans the framing UP at the same size: shift down through the
        // source, the floor fading to black below (FitMock's bottom fill).
        const shift = clamp01(vPos) * 0.3 * h0;
        return {
            x,
            y: Math.min(y0 + shift, y0 + h0 - 0.05),
            w,
            h: Math.max(0.05, h0 - shift),
        };
    }, [isBox, crop, zoom, coverRect, vPos]);

    // The reset button ("Whole image" / "Center") is a no-op when the framing is
    // already at its default — disable it then and explain what to do instead via
    // a tooltip, so it reads as state rather than a dead control.
    const cropIsWhole = !crop || (crop.x === 0 && crop.y === 0 && crop.w === 1 && crop.h === 1);
    const focusIsCentered = focusX === 0.5 && focusY === 0.5;
    const resetAtDefault = isBox ? cropIsWhole : focusIsCentered;
    const resetTip = resetAtDefault
        ? isBox
            ? 'Drag on the photo to crop a region'
            : 'Drag on the photo to set the focal point'
        : isBox
          ? 'Reset the crop to the whole image'
          : 'Re-centre the focal point';

    return (
        <div
            className={
                compact ? 'flex flex-col gap-2' : 'bg-surface border border-border rounded-lg p-3'
            }
        >
            <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
                {!compact && <h3 className="text-sm font-medium text-fg">Crop framing</h3>}
                <div className="flex items-center gap-1 flex-wrap">
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
                    {/* Span wrapper carries the tooltip: a disabled <button>
                        doesn't reliably fire native title tooltips cross-browser. */}
                    <span title={resetTip} className="inline-flex">
                        <Button
                            onClick={() => (isBox ? setCrop(FULL_CROP) : onChange(0.5, 0.5))}
                            variant="secondary"
                            icon={isBox ? 'crop_free' : 'filter_center_focus'}
                            size="small"
                            disabled={resetAtDefault}
                        >
                            {isBox ? 'Whole image' : 'Center'}
                        </Button>
                    </span>
                </div>
            </div>
            <p className="text-xs text-fg-subtle mb-2">
                {FRAMING_HELP[fitMode] || FRAMING_HELP.cover}
            </p>
            {/* Zoom / Vertical position sliders moved to the right-column FRAMING
                group so they are always visible (the canvas math below still reads
                zoom/vPos). */}
            <div className={compact ? '' : 'flex gap-3 items-start'}>
                <div
                    ref={wrapRef}
                    className={`relative leading-none select-none overflow-hidden rounded cursor-crosshair ${
                        compact ? 'block w-full' : 'inline-block min-w-0'
                    }`}
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
                {!compact && (
                    <FitMock
                        imageUrl={imageUrl}
                        ratio={ratio}
                        crop={mockCrop}
                        vPos={isBox ? vPos : 0}
                        label={mockLabel}
                        labelYFrac={labelYFrac}
                    />
                )}
            </div>
        </div>
    );
};

// ─── Picker grid ───────────────────────────────────────────────────────────

// Custom-upload body shown when a picker's source is 'Upload' — the chosen file
// (with Remove) or an upload prompt. Header mirrors Picker so the SourceSelector
// sits in the same place.
const UploadArtCard = ({ label, headerRight, custom, onFile, onClear }) => (
    <div className="bg-surface border border-border rounded-lg p-3">
        <div className="flex items-center justify-between gap-2 mb-2">
            <h3 className="text-sm font-medium text-fg">{label}</h3>
            {headerRight}
        </div>
        {custom ? (
            <div className="flex items-center gap-3 rounded-md border-2 border-primary bg-surface-alt p-2">
                <img
                    src={custom.url}
                    alt="Uploaded"
                    className="h-16 w-auto max-w-[60%] object-contain rounded"
                />
                <span className="flex-1 truncate text-xs text-fg-muted">{custom.name}</span>
                <Button onClick={onClear} variant="secondary" icon="close" size="small">
                    Remove
                </Button>
            </div>
        ) : (
            <label className="flex flex-col items-center justify-center gap-1 rounded-md border-2 border-dashed border-border text-fg-subtle text-xs py-6 cursor-pointer hover:border-primary">
                <span className="material-symbols-outlined">upload</span>
                Upload an image
                <input type="file" accept="image/*" className="hidden" onChange={onFile} />
            </label>
        )}
    </div>
);

const Picker = ({
    label,
    items,
    loading,
    selected,
    onSelect,
    aspect,
    onBlack,
    emptyText,
    headerRight,
}) => {
    // Wide 16:9 backdrops are too small to judge at 3 columns, so give them 2
    // (and a taller scroll area to keep a comfortable number in view). Portrait
    // posters/season art stay at 3 — they're tall enough to read already.
    const wide = aspect === 'aspect-video';
    const gridCls = wide
        ? 'grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-96 overflow-auto'
        : 'grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-72 overflow-auto';
    return (
        <div className="bg-surface border border-border rounded-lg p-3">
            <div className="flex items-center justify-between gap-2 mb-2">
                <h3 className="text-sm font-medium text-fg">{label}</h3>
                {headerRight}
            </div>
            {loading ? (
                <div className="text-xs text-fg-subtle py-4">Loading…</div>
            ) : items.length === 0 ? (
                <div className="text-xs text-fg-subtle py-2">{emptyText}</div>
            ) : (
                <div className={gridCls}>
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
                                        : 'border-border hover:border-primary'
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
                                        <span className="material-symbols-outlined text-sm">
                                            check
                                        </span>
                                    </span>
                                )}
                                {/* Resolution in the TOP-LEFT corner — kept off the
                                bottom so it can't run into the language badge, and
                                off the top-right so it clears the selected check. */}
                                {it.width ? (
                                    <span className="absolute top-0 left-0 text-[11px] font-mono text-white bg-black/60 px-1">
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
};

// ─── CL2K guide overlay ──────────────────────────────────────────────────────

// The template's own guides, drawn over a 2:3 poster preview as Photoshop-style
// cyan lines. Verified 2026-06-13 against the embedded guide resources of the
// PSDs in refs/ (template + finished creator posters — all carry the identical
// set: x 100/200/500/800/900, y 1100/1319/1352/1375; the 150/850 pair is the
// creator's own 700px addition). Positions are fractions of the 1000×1500
// canvas, so the overlay lines up with any rendered preview. Each line explains
// itself on hover (what the guide means) — that's the point of the overlay,
// since the lines alone are cryptic. Inline styles only — this must not depend
// on utility classes existing.
const CL2K_GUIDES = [
    { label: 'Max logo width', o: 'x', p: 100 },
    { label: 'Recommended logo width (700px box) — the creator’s usual width', o: 'x', p: 150 },
    { label: 'Main logo width (600px box)', o: 'x', p: 200 },
    { label: 'Main logo width (600px box)', o: 'x', p: 800 },
    { label: 'Recommended logo width (700px box) — the creator’s usual width', o: 'x', p: 850 },
    { label: 'Max logo width', o: 'x', p: 900 },
    {
        label: 'Main logo height — logos shouldn’t rise above this line',
        o: 'y',
        p: CL2K_LOGO_ZONE_TOP,
    },
    {
        label: 'Collection logo bottom — collection logos sit on this line',
        o: 'y',
        p: CL2K_LOGO_BASELINE_COLLECTION,
    },
    {
        label: 'Main logo bottom — movie/show logos sit on this line',
        o: 'y',
        p: CL2K_LOGO_BASELINE_MAIN,
    },
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

// CL2K-guides toggle pill (the row beside it supplies the "CL2K guides" label).
const GuidesToggle = ({ show, onChange }) => (
    <Toggle checked={show} onChange={onChange} label="Toggle CL2K guides" />
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
    invert, // invert logo: white -> transparent, black -> white (plate/sticker art)
    onInvert,
    touchUpUrl, // processed (un-flipped) logo for the B/W touch-up brush
    onFlipMask,
    source, // optional per-picker source ('tmdb'|'fanart'|'plex'|'upload')
    onSource,
    emptyText = 'No logos from this source — a text wordmark is used as fallback.',
    // Pure-presentational split for the 3-column studio: 'picker' renders only the
    // source tabs + grid (left column), 'controls' renders only the colour-mode
    // tabs + sliders + touch-up (right column). Undefined = the whole card (the
    // LogoAssetPanel call site, unchanged). No handler/state logic differs by
    // variant — props still flow identically.
    variant,
}) => {
    const [showTouchUp, setShowTouchUp] = useState(false);
    // Presentational split: 'picker' = grid only; 'controls' = colour mode +
    // sliders + invert (no touch-up); 'touchup' = the B/W touch-up brush only;
    // undefined = the whole card (LogoAssetPanel call site, unchanged).
    const showPicker = variant !== 'controls' && variant !== 'touchup';
    const showControls = variant !== 'picker' && variant !== 'touchup';
    const showTouchUpSection = variant !== 'picker' && variant !== 'controls';
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
    const colorTabs = onWhiten && (
        <div className="flex gap-1 p-1 rounded-lg bg-surface-inset border border-border">
            <button
                type="button"
                className={`flex-1 text-center px-3 py-1.5 rounded-md text-xs ${
                    whiten ? 'bg-primary text-white font-semibold' : 'text-fg-muted hover:text-fg'
                }`}
                onClick={() => onWhiten(true)}
                title="CL2K two-tone: white fills, black keylines"
            >
                CL2K white
            </button>
            <button
                type="button"
                className={`flex-1 text-center px-3 py-1.5 rounded-md text-xs ${
                    !whiten ? 'bg-primary text-white font-semibold' : 'text-fg-muted hover:text-fg'
                }`}
                onClick={() => onWhiten(false)}
                title="Keep the logo's original colors"
            >
                Original
            </button>
        </div>
    );
    const cardCls = variant
        ? 'flex flex-col gap-3'
        : 'bg-surface border border-border rounded-lg p-3';
    return (
        <div className={cardCls}>
            {showPicker && (
                <>
                    <div className="flex items-center justify-between mb-2">
                        {variant ? (
                            <span className="font-mono text-[10px] tracking-wide uppercase text-fg-subtle">
                                Logo / wordmark
                            </span>
                        ) : (
                            <h3 className="text-sm font-medium text-fg">{label}</h3>
                        )}
                        <div className="flex items-center gap-1.5">
                            {!variant && colorTabs}
                            {onSource ? (
                                <SourceSelector value={source} onChange={onSource} />
                            ) : (
                                <label className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs border border-border text-fg-muted hover:border-primary cursor-pointer">
                                    <span className="material-symbols-outlined text-sm">
                                        upload
                                    </span>
                                    Upload custom
                                    <input
                                        type="file"
                                        accept="image/*"
                                        className="hidden"
                                        onChange={onFile}
                                    />
                                </label>
                            )}
                        </div>
                    </div>
                    {/* 'Upload' source with nothing uploaded yet → a dropzone (the chosen
                file then shows in the customLogo card below). */}
                    {onSource && source === 'upload' && !customLogo ? (
                        <label className="flex flex-col items-center justify-center gap-1 rounded-md border-2 border-dashed border-border text-fg-subtle text-xs py-6 cursor-pointer hover:border-primary">
                            <span className="material-symbols-outlined">upload</span>
                            Upload a logo (PNG, transparent)
                            <input
                                type="file"
                                accept="image/*"
                                className="hidden"
                                onChange={onFile}
                            />
                        </label>
                    ) : customLogo ? (
                        <div className="flex items-center gap-3 rounded-md border-2 border-primary bg-black p-2">
                            <img
                                src={customLogo.url}
                                alt="Custom logo"
                                className="h-14 w-auto max-w-[60%] object-contain"
                            />
                            <span className="flex-1 truncate text-xs text-fg-muted">
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
                        <div className="text-xs text-fg-subtle py-4">Loading…</div>
                    ) : logos.length === 0 ? (
                        <div className="text-xs text-fg-subtle py-2">{emptyText}</div>
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
                                                : 'border-border hover:border-primary'
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
                </>
            )}
            {showControls && variant && colorTabs}
            {onScale && showControls && (
                <label className="mt-2 flex items-center gap-2 text-xs text-fg-muted">
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
            {onYOffset && showControls && (
                <label className="mt-2 flex items-center gap-2 text-xs text-fg-muted">
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
            {/* Invert logo: plate/sticker art (a solid light plate with dark text)
                whitens into a white box — the OPPOSITE of a clearlogo. Inverting
                makes darkness the opacity: black text -> solid white, the plate ->
                transparent. Only meaningful on the CL2K-white two-tone. */}
            {onInvert && whiten && showControls && (
                <div className="mt-2 flex items-center justify-between gap-3">
                    <div className="min-w-0">
                        <span className="text-xs text-fg-muted">Invert logo</span>
                        <span className="block text-[11px] text-fg-subtle">
                            white becomes transparent, black becomes white (for plate/sticker logos)
                        </span>
                    </div>
                    <Toggle checked={!!invert} onChange={onInvert} label="Invert logo" />
                </div>
            )}
            {/* B/W touch-up: a global two-tone map can't decide interior accents
                that share saturation + luma with their surroundings — brush those
                regions to flip black↔white. Drawn over the UN-flipped processed
                logo so the accumulated strokes stay valid; the live overlay and
                the render apply the flip. */}
            {onFlipMask && touchUpUrl && whiten && showTouchUpSection && (
                <div className="mt-2">
                    <button
                        type="button"
                        onClick={() => setShowTouchUp(s => !s)}
                        className="px-2.5 py-1 text-xs rounded-md border bg-surface text-fg-muted border-border hover:border-primary"
                    >
                        {showTouchUp ? 'Hide colour fix' : 'Fix a mis-coloured area (optional)'}
                    </button>
                    {showTouchUp && (
                        <div className="mt-2">
                            <p className="text-xs text-fg-subtle mb-1">
                                <span className="text-fg-muted">
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
            {showControls && (
                <p className="mt-2 text-xs text-fg-subtle">
                    Whitened, trimmed and placed on the CL2K guides automatically — it moves live in
                    the preview as you drag.
                    {onScale && (
                        <>
                            {' '}
                            Size 100% = the 700px recommended guide box; the 800px line is the
                            template’s suggested max (a guideline, not enforced).
                        </>
                    )}
                    {onYOffset && (
                        <>
                            {' '}
                            Position 0 = the template’s logo-bottom guide (where finished CL2K
                            posters sit); negative moves the logo up, positive down.
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
                            className="text-fg underline hover:no-underline"
                        >
                            Reset to CL2K defaults
                        </button>
                    )}
                </p>
            )}
        </div>
    );
};

// ─── Square art tab ─────────────────────────────────────────────────────────

// Drag a 1:1 cover-crop box over the source art to choose what fills the square.
// Zoom + Focus-Y sliders for the asset framers (Background / Square), surfaced in
// the right-column FRAMING group to mirror the Poster tab. The frame itself (fit
// tabs + drag-to-pan) stays in the center SquareFramer; these drive the same
// zoom / focusY state, so they stay in sync with a drag.
const FramingSliders = ({ zoom, setZoom, focusY, setFocusY }) => (
    <>
        <div>
            <div className="flex justify-between mb-1.5">
                <span className="text-sm text-fg-muted">Zoom</span>
                <span className="font-mono text-xs text-fg-subtle">{(zoom ?? 1).toFixed(2)}×</span>
            </div>
            <input
                type="range"
                min="0.5"
                max="3"
                step="0.05"
                value={zoom ?? 1}
                onChange={e => setZoom(Number(e.target.value))}
                className="w-full"
            />
        </div>
        <div>
            <div className="flex justify-between mb-1.5">
                <span className="text-sm text-fg-muted">Focus Y</span>
                <span className="font-mono text-xs text-fg-subtle">
                    {(focusY ?? 0.5).toFixed(2)}
                </span>
            </div>
            <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                value={focusY ?? 0.5}
                onChange={e => setFocusY(Number(e.target.value))}
                className="w-full"
            />
        </div>
    </>
);

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
        const z = Math.max(CONTROL_RANGES.zoom.min, Math.min(zoom || 1, CONTROL_RANGES.zoom.max));
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
                : 'bg-surface text-fg-muted border-border hover:border-primary'
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
                <h3 className="text-sm font-medium text-fg">{title}</h3>
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
            <p className="text-xs text-fg-subtle mb-2">
                {fitMode === 'fit'
                    ? 'Fit shows the whole image on black. Zoom (in the Framing panel) fills more; drag to pan when zoomed.'
                    : `Fill crops to the ${frameName} — drag to choose what stays. Zoom (in the Framing panel) punches in tighter.`}
            </p>
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
        <label className="flex items-center gap-2 text-sm text-fg-muted">
            <span className="w-28">Season</span>
            <input
                type="number"
                min="0"
                max="99"
                value={value}
                onChange={e => onChange(e.target.value)}
                placeholder="blank = the show itself"
                className="flex-1 bg-surface border border-border rounded px-2 py-1 text-sm text-fg"
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
    <p className="text-xs text-fg-subtle">
        Applies on the next Asset Renamerr run — the CL2K output directory must be one of Poster
        Renamerr&apos;s source dirs for the file to be scanned.
    </p>
);

const SquareArtPanel = ({ item, artBySource, loadingArt, saveTargets, toast }) => {
    const [backdrop, setBackdrop] = useState(null); // file_path | url
    const [customBg, setCustomBg] = useState(null); // { b64, url, name }
    const [bgSource, setBgSource] = useState('tmdb');
    const backdrops = artBySource[bgSource]?.backdrops || [];
    const posters = artBySource[bgSource]?.posters || [];
    // Leaving the Upload source clears the custom image so a provider pick wins.
    const onBgSource = s => {
        setBgSource(s);
        if (s !== 'upload') setCustomBg(null);
    };
    const pickBackdrop = p => {
        setBackdrop(p);
        setCustomBg(null);
    };
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

    const sig = `${customSig(customBg) || backdrop}|${focusX}|${focusY}|${fitMode}|${zoom}`;
    useEffect(() => {
        if (!hasSrc) return undefined;
        let cancelled = false;
        const aborter = new AbortController();
        const t = setTimeout(async () => {
            setPreviewing(true);
            try {
                const blob = await cl2kMakerAPI.squarePreview(reqRef.current, {
                    signal: aborter.signal,
                });
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
        }, 300);
        return () => {
            cancelled = true;
            aborter.abort();
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
        <section className="mt-4 grid grid-cols-1 xl:grid-cols-[320px_minmax(0,1fr)_300px] gap-4 items-start">
            {/* LEFT: source pickers */}
            <div className="bg-surface border border-border rounded-[12px] p-4 flex flex-col gap-[18px]">
                {bgSource === 'upload' ? (
                    <UploadArtCard
                        label="Source art (backdrop)"
                        headerRight={<SourceSelector value={bgSource} onChange={onBgSource} />}
                        custom={customBg}
                        onFile={onFile}
                        onClear={() => setCustomBg(null)}
                    />
                ) : (
                    <Picker
                        label="Source art (backdrop)"
                        headerRight={<SourceSelector value={bgSource} onChange={onBgSource} />}
                        items={backdrops}
                        loading={loadingArt}
                        selected={backdrop}
                        onSelect={pickBackdrop}
                        aspect="aspect-video"
                        emptyText={
                            bgSource === 'plex' &&
                            artBySource.plex?.reason &&
                            !backdrops.length &&
                            !posters.length
                                ? artBySource.plex.reason
                                : 'No backdrops from this source.'
                        }
                    />
                )}
                {/* Posters as a source too: pick a 2:3 poster and the framer below
                    crops it to fit (fill/fit + zoom/drag). Lets a larger poster
                    become square art or a 16:9 background. */}
                {bgSource !== 'upload' && posters.length > 0 && (
                    <Picker
                        label="Poster (crop to fit)"
                        items={posters}
                        loading={loadingArt}
                        selected={backdrop}
                        onSelect={pickBackdrop}
                        aspect="aspect-[2/3]"
                        emptyText="No posters from this source."
                    />
                )}
            </div>

            {/* CENTER: sticky preview + framer + output */}
            <section className="sticky top-0 self-start flex flex-col items-center gap-[13px]">
                <div className="relative w-full max-w-[420px] aspect-square bg-black rounded-[10px] overflow-hidden flex items-center justify-center border border-border shadow-lg">
                    {hasSrc && previewUrl ? (
                        <>
                            <img
                                src={previewUrl}
                                alt="Square art preview"
                                className="w-full h-full object-contain"
                            />
                            <PreviewRefreshing active={previewing} />
                        </>
                    ) : (
                        <span className="text-xs text-fg-subtle px-4 text-center">
                            {hasSrc ? 'Rendering preview…' : 'Pick or upload source art.'}
                        </span>
                    )}
                </div>

                {srcUrl && (
                    <div className="w-full max-w-[420px]">
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
                    </div>
                )}

                <div className="w-full max-w-[420px] flex flex-col gap-2">
                    <AssetSeasonField
                        show={item.kind === 'show'}
                        value={seasonNumber}
                        onChange={setSeasonNumber}
                    />
                    <p className="text-xs text-fg-subtle">
                        Saved as{' '}
                        <span className="text-fg-muted">
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
            </section>

            {/* RIGHT: framing + history accordion */}
            <section className="bg-surface border border-border rounded-[12px] p-4 flex flex-col gap-3.5">
                <div className="flex flex-col gap-3">
                    <StudioGroupLabel>Framing</StudioGroupLabel>
                    <FramingSliders
                        zoom={zoom}
                        setZoom={setZoom}
                        focusY={focusY}
                        setFocusY={setFocusY}
                    />
                </div>
                <StudioAccordion title="Recently generated">
                    <HistorySection toast={toast} />
                </StudioAccordion>
            </section>
        </section>
    );
};

// ─── Background art tab ─────────────────────────────────────────────────────

const BackgroundArtPanel = ({ item, artBySource, loadingArt, saveTargets, toast }) => {
    const [backdrop, setBackdrop] = useState(null); // file_path | url
    const [customBg, setCustomBg] = useState(null); // { b64, url, name }
    const [bgSource, setBgSource] = useState('tmdb');
    const backdrops = artBySource[bgSource]?.backdrops || [];
    const posters = artBySource[bgSource]?.posters || [];
    const onBgSource = s => {
        setBgSource(s);
        if (s !== 'upload') setCustomBg(null);
    };
    const pickBackdrop = p => {
        setBackdrop(p);
        setCustomBg(null);
    };
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
    const sig = `${customSig(customBg) || backdrop}|${focusX}|${focusY}|${fitMode}|${zoom}`;
    useEffect(() => {
        if (!hasSrc) return undefined;
        let cancelled = false;
        const aborter = new AbortController();
        const t = setTimeout(async () => {
            setPreviewing(true);
            try {
                const blob = await cl2kMakerAPI.backgroundPreview(reqRef.current, {
                    signal: aborter.signal,
                });
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
        }, 300);
        return () => {
            cancelled = true;
            aborter.abort();
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

    return (
        <section className="mt-4 grid grid-cols-1 xl:grid-cols-[320px_minmax(0,1fr)_300px] gap-4 items-start">
            {/* LEFT: source pickers */}
            <div className="bg-surface border border-border rounded-[12px] p-4 flex flex-col gap-[18px]">
                {bgSource === 'upload' ? (
                    <UploadArtCard
                        label="Source art (backdrop)"
                        headerRight={<SourceSelector value={bgSource} onChange={onBgSource} />}
                        custom={customBg}
                        onFile={onFile}
                        onClear={() => setCustomBg(null)}
                    />
                ) : (
                    <Picker
                        label="Source art (backdrop)"
                        headerRight={<SourceSelector value={bgSource} onChange={onBgSource} />}
                        items={backdrops}
                        loading={loadingArt}
                        selected={backdrop}
                        onSelect={pickBackdrop}
                        aspect="aspect-video"
                        emptyText={
                            bgSource === 'plex' &&
                            artBySource.plex?.reason &&
                            !backdrops.length &&
                            !posters.length
                                ? artBySource.plex.reason
                                : 'No backdrops from this source.'
                        }
                    />
                )}
                {/* Posters as a source too: pick a 2:3 poster and the framer below
                    crops it to fit (fill/fit + zoom/drag). Lets a larger poster
                    become square art or a 16:9 background. */}
                {bgSource !== 'upload' && posters.length > 0 && (
                    <Picker
                        label="Poster (crop to fit)"
                        items={posters}
                        loading={loadingArt}
                        selected={backdrop}
                        onSelect={pickBackdrop}
                        aspect="aspect-[2/3]"
                        emptyText="No posters from this source."
                    />
                )}
            </div>

            {/* CENTER: sticky preview + framer + output */}
            <section className="sticky top-0 self-start flex flex-col items-center gap-[13px]">
                <div className="relative w-full max-w-[560px] aspect-video bg-black rounded-[10px] overflow-hidden flex items-center justify-center border border-border shadow-lg">
                    {hasSrc && previewUrl ? (
                        <>
                            <img
                                src={previewUrl}
                                alt="Background art preview"
                                className="w-full h-full object-contain"
                            />
                            <PreviewRefreshing active={previewing} />
                        </>
                    ) : (
                        <span className="text-xs text-fg-subtle px-4 text-center">
                            {hasSrc ? 'Rendering preview…' : 'Pick or upload source art.'}
                        </span>
                    )}
                </div>

                {srcUrl && (
                    <div className="w-full max-w-[560px]">
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
                    </div>
                )}

                <div className="w-full max-w-[560px] flex flex-col gap-2">
                    <AssetSeasonField
                        show={item.kind === 'show'}
                        value={seasonNumber}
                        onChange={setSeasonNumber}
                    />
                    <p className="text-xs text-fg-subtle">
                        Saved as{' '}
                        <span className="text-fg-muted">
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
            </section>

            {/* RIGHT: FRAMING (resolution) + history accordion */}
            <section className="bg-surface border border-border rounded-[12px] p-4 flex flex-col gap-3.5">
                <div className="flex flex-col gap-3">
                    <StudioGroupLabel>Framing</StudioGroupLabel>
                    <div className="flex items-center justify-between">
                        <span className="text-sm text-fg-muted">
                            Resolution{' '}
                            <span className="font-mono text-xs text-fg-subtle">
                                {resolution === '4k' ? '3840×2160' : '1920×1080'}
                            </span>
                        </span>
                        <div className="flex gap-1 p-1 rounded-lg bg-surface-inset border border-border">
                            <button
                                type="button"
                                onClick={() => setResolution('1080p')}
                                className={`px-3 py-1.5 rounded-md font-mono text-xs ${
                                    resolution !== '4k'
                                        ? 'bg-primary text-white font-semibold'
                                        : 'text-fg-muted hover:text-fg'
                                }`}
                            >
                                1080p
                            </button>
                            <button
                                type="button"
                                onClick={() => setResolution('4k')}
                                className={`px-3 py-1.5 rounded-md font-mono text-xs ${
                                    resolution === '4k'
                                        ? 'bg-primary text-white font-semibold'
                                        : 'text-fg-muted hover:text-fg'
                                }`}
                            >
                                4K
                            </button>
                        </div>
                    </div>
                    <FramingSliders
                        zoom={zoom}
                        setZoom={setZoom}
                        focusY={focusY}
                        setFocusY={setFocusY}
                    />
                </div>
                <StudioAccordion title="Recently generated">
                    <HistorySection toast={toast} />
                </StudioAccordion>
            </section>
        </section>
    );
};

// ─── Logo asset tab ─────────────────────────────────────────────────────────

const LogoAssetPanel = ({ item, artBySource, loadingArt, saveTargets, toast }) => {
    const [logo, setLogo] = useState(null); // file_path
    const [customLogo, setCustomLogo] = useState(null); // { b64, url, name }
    const [logoSource, setLogoSource] = useState('tmdb');
    // Switching OFF Upload clears the custom logo (same rule as every picker).
    const onLogoSource = s => {
        setLogoSource(s);
        if (s !== 'upload') setCustomLogo(null);
    };
    const logos = useMemo(
        () => sortWordmarkFirst(artBySource[logoSource]?.logos || []),
        [artBySource, logoSource]
    );
    const [whiten, setWhiten] = useState(false);
    // Invert logo: white -> transparent, black -> white (plate/sticker art).
    const [invert, setInvert] = useState(false);
    const [previewUrl, setPreviewUrl] = useState(null); // UN-flipped (brush base)
    const [previewing, setPreviewing] = useState(false);
    const [busy, setBusy] = useState(false);
    const hasLogo = !!(logo || customLogo);

    // B/W touch-up strokes are keyed to the (logo, whiten, invert) they were
    // drawn over so a stale mask becomes a derived no-op (same as the Builder).
    const flipKey = `${customSig(customLogo) || logo}|${whiten}|${invert}`;
    const [flip, setFlip] = useState(null); // { key, b64 }
    const flipB64 = flip && flip.key === flipKey ? flip.b64 : null;
    const setFlipB64 = useCallback(b64 => setFlip(b64 ? { key: flipKey, b64 } : null), [flipKey]);
    // The B/W touch-up brush now lives in a StudioAccordion (its own open state),
    // so no separate showTouchUp toggle is needed.
    const [flipped, setFlipped] = useState(null); // { forB64, url } — flipped preview

    const setCustomExclusive = useCallback(c => {
        setCustomLogo(c);
        if (c) setLogo(null);
    }, []);

    // ─── Extract a logo from a poster (no AI) ──────────────────────────────────
    // Brush over a title on a poster; the key lifts it into a transparent logo,
    // which becomes the custom logo and flows through the same whiten/save. White
    // mode keys a white title by brightness; coloured mode keys it by colour.
    const [extractOpen, setExtractOpen] = useState(false);
    const [posterSource, setPosterSource] = useState('tmdb');
    const [posterPath, setPosterPath] = useState(null);
    const [customPoster, setCustomPoster] = useState(null); // { b64, url, name }
    const [extractMask, setExtractMask] = useState(null);
    const [extractMode, setExtractMode] = useState('white'); // 'white' | 'subject'
    const [extracting, setExtracting] = useState(false);
    const posters = artBySource[posterSource]?.posters || [];
    const posterUrl = customPoster?.url || (posterPath ? urlForPath(posterPath) : null);
    const onPosterSource = s => {
        setPosterSource(s);
        if (s !== 'upload') setCustomPoster(null);
    };
    const pickPoster = p => {
        setPosterPath(p);
        setCustomPoster(null);
        setExtractMask(null);
    };
    const onPosterFile = e => {
        const f = e.target.files?.[0];
        e.target.value = '';
        if (!f) return;
        const reader = new FileReader();
        reader.onload = () => {
            const url = String(reader.result);
            setCustomPoster({ b64: url.split(',').pop(), url, name: f.name });
            setPosterPath(null);
            setExtractMask(null);
        };
        reader.readAsDataURL(f);
    };
    const onExtract = async () => {
        if (!posterUrl) return;
        setExtracting(true);
        try {
            const blob = await cl2kMakerAPI.extractLogo({
                image_path: customPoster ? null : posterPath,
                image_b64: customPoster?.b64 || null,
                mask_b64: extractMask,
                mode: extractMode,
            });
            const url = await new Promise(resolve => {
                const fr = new FileReader();
                fr.onload = () => resolve(String(fr.result));
                fr.readAsDataURL(blob);
            });
            setCustomExclusive({ b64: url.split(',').pop(), url, name: 'extracted-logo.png' });
            setExtractOpen(false);
        } catch (err) {
            toast.error(err.message || 'Extraction failed');
        } finally {
            setExtracting(false);
        }
    };

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
            invert,
            flip_b64: flipB64,
            save_local: saveTargets.saveLocal,
            upload_gdrive: saveTargets.uploadGdrive,
        }),
        [
            item,
            logo,
            customLogo,
            whiten,
            invert,
            flipB64,
            saveTargets.saveLocal,
            saveTargets.uploadGdrive,
        ]
    );
    const reqRef = useRef(req);
    useEffect(() => {
        reqRef.current = req;
    }, [req]);

    // Brush base: the processed logo WITHOUT the flip — it must stay stable as
    // strokes land, or the accumulated mask would be drawn over a moving target.
    const sig = `${customSig(customLogo) || logo}|${whiten}|${invert}`;
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

    // Download the processed logo (whiten/invert/flip applied) straight to the PC.
    const onDownload = async () => {
        setBusy(true);
        try {
            const blob = await cl2kMakerAPI.logoAssetPreview(req);
            downloadBlob(blob, `${item.title}${item.year ? ` (${item.year})` : ''} - Logo.png`);
        } catch (err) {
            toast.error(err.message || 'Download failed');
        } finally {
            setBusy(false);
        }
    };

    const seg = on =>
        `px-3 py-1 text-sm rounded-md border ${
            on
                ? 'bg-primary text-white border-primary'
                : 'bg-surface text-fg-muted border-border hover:border-primary'
        }`;

    return (
        <section className="mt-4 grid grid-cols-1 xl:grid-cols-[320px_minmax(0,1fr)_300px] gap-4 items-start">
            {/* LEFT: logo source picker */}
            <div className="bg-surface border border-border rounded-[12px] p-4 flex flex-col gap-[18px]">
                <LogoSelector
                    variant="picker"
                    label="Logo"
                    logos={logos}
                    loading={loadingArt}
                    selected={logo}
                    onSelect={setLogo}
                    customLogo={customLogo}
                    onCustomChange={setCustomExclusive}
                    source={logoSource}
                    onSource={onLogoSource}
                    emptyText={
                        logoSource === 'plex' && artBySource.plex?.reason && !logos.length
                            ? artBySource.plex.reason
                            : 'No logos from this source — switch source or Upload a custom PNG.'
                    }
                />
            </div>

            {/* CENTER: sticky checkerboard preview + output */}
            <section className="sticky top-0 self-start flex flex-col items-center gap-[13px]">
                <div
                    className="relative w-full max-w-[480px] aspect-video rounded-[10px] overflow-hidden flex items-center justify-center border border-border shadow-lg"
                    style={{
                        backgroundImage: 'repeating-conic-gradient(#3a3a4a 0% 25%, #2a2a38 0% 50%)',
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
                        <span className="text-xs text-fg-subtle px-4 text-center bg-black/40 rounded px-2 py-1">
                            {hasLogo ? 'Rendering preview…' : 'Pick or upload a logo.'}
                        </span>
                    )}
                </div>
                <div className="w-full max-w-[480px] flex flex-col gap-2">
                    <p className="text-xs text-fg-subtle">
                        Filed as{' '}
                        <span className="text-fg-muted">Title (Year) {'{ids}'} - Logo.png</span> and
                        applied to Plex/Kometa via Asset Renamerr — separate from any square art.
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
                    <button
                        type="button"
                        onClick={onDownload}
                        disabled={!hasLogo || busy || previewing}
                        className="px-3 py-1.5 text-sm rounded-md border bg-surface text-fg-muted border-border hover:border-primary disabled:opacity-50"
                    >
                        Download to PC
                    </button>
                </div>
            </section>

            {/* RIGHT: colour controls + extract / touch-up / history accordions */}
            <section className="bg-surface border border-border rounded-[12px] p-4 flex flex-col gap-3.5">
                <div className="flex flex-col gap-3">
                    <StudioGroupLabel>Colour</StudioGroupLabel>
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
                    <p className="text-xs text-fg-subtle">
                        Original keeps the clear logo&apos;s colours (the usual Plex/Kometa logo
                        asset). CL2K white recolours it to the CL2K two-tone — white fills, black
                        keylines — like a CL2K poster logo.
                    </p>
                    {whiten && (
                        <label className="flex items-center gap-2 text-xs text-fg-muted cursor-pointer">
                            <input
                                type="checkbox"
                                checked={invert}
                                onChange={e => setInvert(e.target.checked)}
                            />
                            Invert logo
                            <span className="text-fg-subtle">
                                — white becomes transparent, black becomes white (for plate/sticker
                                logos)
                            </span>
                        </label>
                    )}
                </div>

                {/* ACCORDION: Extract logo from poster (controlled — onExtract
                    collapses it on success via setExtractOpen). */}
                <StudioAccordion
                    title="Extract logo from poster"
                    open={extractOpen}
                    onToggle={() => setExtractOpen(o => !o)}
                >
                    <div className="flex flex-col gap-3">
                        <p className="text-xs text-fg-subtle">
                            Pull a white title straight off a poster — no OpenAI. Pick a poster,
                            brush over the title (a loose scribble is fine; keep off bright areas),
                            then Extract. The result becomes your logo below.
                        </p>
                        {posterSource === 'upload' ? (
                            <UploadArtCard
                                label="Poster"
                                headerRight={
                                    <SourceSelector
                                        value={posterSource}
                                        onChange={onPosterSource}
                                    />
                                }
                                custom={customPoster}
                                onFile={onPosterFile}
                                onClear={() => setCustomPoster(null)}
                            />
                        ) : (
                            <Picker
                                label="Poster"
                                headerRight={
                                    <SourceSelector
                                        value={posterSource}
                                        onChange={onPosterSource}
                                    />
                                }
                                items={posters}
                                loading={loadingArt}
                                selected={posterPath}
                                onSelect={pickPoster}
                                aspect="aspect-[2/3]"
                                emptyText={
                                    posterSource === 'plex' &&
                                    artBySource.plex?.reason &&
                                    !posters.length
                                        ? artBySource.plex.reason
                                        : 'No posters from this source — switch source or Upload one.'
                                }
                            />
                        )}
                        {posterUrl && (
                            <div>
                                <div className="flex items-center gap-2 mb-1">
                                    <button
                                        type="button"
                                        className={seg(extractMode === 'white')}
                                        onClick={() => setExtractMode('white')}
                                    >
                                        White title
                                    </button>
                                    <button
                                        type="button"
                                        className={seg(extractMode === 'subject')}
                                        onClick={() => setExtractMode('subject')}
                                    >
                                        Coloured title
                                    </button>
                                </div>
                                <p className="text-xs text-fg-subtle mb-1">
                                    {extractMode === 'subject'
                                        ? 'Brush over the coloured title (keep close to it):'
                                        : 'Brush over the white title:'}
                                </p>
                                <div className="bg-black rounded p-1 inline-block max-w-full">
                                    <BrushMask
                                        imageUrl={posterUrl}
                                        brushSize={18}
                                        onMaskChange={setExtractMask}
                                    />
                                </div>
                            </div>
                        )}
                        <LoadingButton
                            onClick={onExtract}
                            loading={extracting}
                            disabled={!posterUrl || !extractMask}
                            icon="content_cut"
                        >
                            Extract logo
                        </LoadingButton>
                    </div>
                </StudioAccordion>

                {/* ACCORDION: Logo touch-up (B/W brush over the processed logo) */}
                {whiten && hasLogo && previewUrl && (
                    <StudioAccordion title="Logo touch-up">
                        <p className="text-xs text-fg-subtle mb-2">
                            <span className="text-fg-muted">
                                Most logos whiten correctly — you can skip this.
                            </span>{' '}
                            Only if a part came out the wrong shade, brush over just those spots to
                            flip them black↔white. Everything you don&apos;t paint is left exactly
                            as shown.
                        </p>
                        <div className="bg-black rounded p-1 inline-block max-w-full">
                            <BrushMask
                                imageUrl={previewUrl}
                                brushSize={10}
                                onMaskChange={setFlipB64}
                            />
                        </div>
                    </StudioAccordion>
                )}

                {/* ACCORDION: Recently generated */}
                <StudioAccordion title="Recently generated">
                    <HistorySection toast={toast} />
                </StudioAccordion>
            </section>
        </section>
    );
};

// ─── Synced-poster picker (browse the GDrive sync cache) ────────────────────

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
                <span className="text-sm font-medium text-fg">Recently generated</span>
                <span className="material-symbols-outlined text-fg-subtle">
                    {open ? 'expand_less' : 'expand_more'}
                </span>
            </button>
            {open && (
                <div className="p-3 border-t border-border-subtle">
                    {loading ? (
                        <Spinner size="small" text="Loading…" />
                    ) : !items || items.length === 0 ? (
                        <div className="text-xs text-fg-subtle">Nothing generated yet.</div>
                    ) : (
                        <ul className="divide-y divide-border text-sm">
                            {items.map((it, idx) => (
                                <li
                                    key={`${it.file || idx}`}
                                    className="py-2 flex items-center justify-between gap-3"
                                >
                                    <span className="text-fg truncate">
                                        {it.title || it.file}
                                        {it.season_number != null && (
                                            <span className="text-fg-subtle">
                                                {' '}
                                                · S{it.season_number}
                                            </span>
                                        )}
                                    </span>
                                    <span className="text-xs text-fg-subtle shrink-0">
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
