import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useApiData } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { postersAPI } from '../../utils/api/posters.js';
import { systemAPI } from '../../utils/api/system.js';
import { copyText } from '../../utils/clipboard.js';
import { buildPosterRequestText, formatId } from '../../utils/posterRequest.js';
import { extensionCapability } from '../../extensions/index.js';
import { Button, IconButton, Modal } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';

// Optional extension hook: (item) => { to, title, ariaLabel, icon } | null.
// Renders an extra per-row action link (e.g. a poster-maker shortcut) when an
// extension registers it; null on main.
const rowActionFor = extensionCapability('unmatchedAssets.rowAction');

const SUMMARY_TYPES = [
    { key: 'movies', label: 'Movies', icon: '🎬' },
    { key: 'series', label: 'Series', icon: '📺' },
    { key: 'seasons', label: 'Seasons', icon: '🗓️' },
    { key: 'collections', label: 'Collections', icon: '🗂️' },
];

// Additional (non-poster) artwork shown behind the "Additional artwork" toggle.
// Banner is intentionally absent (no Plex/Kometa apply path). Order = display.
const ARTWORK_TYPES = [
    { key: 'logo', label: 'Logos', icon: '🅰️' },
    { key: 'background', label: 'Backgrounds', icon: '🌄' },
    { key: 'squareart', label: 'Square art', icon: '🔳' },
];

const TYPE_LABELS = { movie: 'Movie', series: 'Series', collection: 'Collection' };
const TYPE_TABS = [
    { key: 'all', label: 'All' },
    { key: 'movie', label: 'Movies' },
    { key: 'series', label: 'Series' },
    { key: 'collection', label: 'Collections' },
];

const REEL_FILTERS = [
    { key: 'all', label: 'All', match: () => true },
    { key: 'movieshow', label: 'Movie / Show', match: t => t === 'movie' || t === 'show' },
    { key: 'season', label: 'Season', match: t => t === 'season' },
    { key: 'collection', label: 'Collection', match: t => t === 'collection' },
];
const REEL_PAGE_SIZE = 10;

// CL2K / MM2K are the *built* poster styles whose provenance matters — they
// carry a real author. Other styles (GDrive / local fetches) get no tag.
const BUILT_STYLE_TAG = {
    CL2K: ['#a99eff', 'rgba(135,103,247,.32)'],
    MM2K: ['#ffc944', 'rgba(255,201,68,.22)'],
};

/** A single poster in the reel: thumbnail + (for CL2K/MM2K) a source tag and
 *  the builder it came from. */
const ReelPosterCard = ({ poster }) => {
    const [failed, setFailed] = useState(false);
    const styleTag = BUILT_STYLE_TAG[poster.style];
    const builtBy = styleTag ? poster.folder : null;
    return (
        <div className="shrink-0" style={{ width: 112 }}>
            <div
                className="relative rounded-lg overflow-hidden border border-border bg-input shadow-md flex items-center justify-center"
                style={{ aspectRatio: '2 / 3' }}
                title={poster.title || poster.file || ''}
            >
                {failed ? (
                    <span className="material-symbols-outlined text-fg-subtle text-3xl">
                        broken_image
                    </span>
                ) : (
                    <img
                        src={postersAPI.getThumbnailUrl(poster.id, 200)}
                        alt={poster.title || `#${poster.id}`}
                        loading="lazy"
                        className="object-cover"
                        style={{ width: '100%', height: '100%' }}
                        onError={() => setFailed(true)}
                    />
                )}
                {styleTag && (
                    <span
                        className="absolute bottom-1.5 left-1.5 font-mono text-[8px] font-bold tracking-[0.4px] px-1.5 py-0.5 rounded-[4px]"
                        style={{ color: styleTag[0], background: styleTag[1] }}
                    >
                        {poster.style}
                    </span>
                )}
            </div>
            <p className="mt-1.5 text-xs font-medium text-fg-muted text-center truncate">
                {poster.title || `#${poster.id}`}
            </p>
            {builtBy && (
                <p className="font-mono text-[9px] text-fg-subtle text-center truncate">
                    by {builtBy}
                </p>
            )}
        </div>
    );
};

/** Horizontal "movie reel" of recently synced posters with type filters + paging. */
const RecentPosterReel = ({ posters, onRefresh }) => {
    const [filterKey, setFilterKey] = useState('all');
    const [page, setPage] = useState(0);
    const filtered = useMemo(() => {
        const f = REEL_FILTERS.find(x => x.key === filterKey) || REEL_FILTERS[0];
        return posters.filter(p => f.match(p.asset_type));
    }, [posters, filterKey]);
    const pageCount = Math.max(1, Math.ceil(filtered.length / REEL_PAGE_SIZE));
    const safePage = Math.min(page, pageCount - 1);
    const visible = filtered.slice(
        safePage * REEL_PAGE_SIZE,
        safePage * REEL_PAGE_SIZE + REEL_PAGE_SIZE
    );
    const selectFilter = key => {
        setFilterKey(key);
        setPage(0);
    };
    return (
        <section>
            <div className="flex items-center justify-between gap-3 flex-wrap mb-4">
                <h3 className="font-display text-[15px] font-semibold text-fg flex items-center gap-2.5">
                    <span className="w-[7px] h-[7px] rounded-full bg-success" aria-hidden="true" />
                    Recently matched
                </h3>
                <div className="flex items-center gap-2 flex-wrap">
                    <div className="flex flex-wrap gap-1">
                        {REEL_FILTERS.map(f => (
                            <button
                                key={f.key}
                                onClick={() => selectFilter(f.key)}
                                className={`px-3 py-1 text-xs rounded-lg border transition-colors ${
                                    filterKey === f.key
                                        ? 'border-primary/50 bg-primary/15 text-fg'
                                        : 'border-border text-fg-muted hover:text-fg'
                                }`}
                            >
                                {f.label}
                            </button>
                        ))}
                    </div>
                    <span
                        className="text-xs text-fg-subtle text-center"
                        style={{ minWidth: '3rem' }}
                    >
                        {safePage + 1} / {pageCount}
                    </span>
                    <IconButton
                        icon="refresh"
                        variant="ghost"
                        aria-label="Refresh recently synced"
                        onClick={onRefresh}
                    />
                </div>
            </div>
            <div className="flex items-center gap-2">
                <IconButton
                    icon="chevron_left"
                    variant="ghost"
                    aria-label="Previous page"
                    disabled={safePage === 0}
                    onClick={() => setPage(p => Math.max(0, p - 1))}
                />
                <div className="flex-1 overflow-x-auto">
                    <div className="flex gap-3">
                        {visible.map(p => (
                            <ReelPosterCard key={p.id} poster={p} />
                        ))}
                    </div>
                </div>
                <IconButton
                    icon="chevron_right"
                    variant="ghost"
                    aria-label="Next page"
                    disabled={safePage >= pageCount - 1}
                    onClick={() => setPage(p => Math.min(pageCount - 1, p + 1))}
                />
            </div>
        </section>
    );
};

const UNMATCHED_PAGE_SIZE = 50;

/**
 * Shared client-side sort for the unmatched / review / artwork tables.
 * `accessors` maps a column key to a value-extractor. Empty values
 * (null / '' / undefined) always sink to the bottom regardless of
 * direction; a null sort key leaves the rows in their incoming order.
 */
const sortRows = (rows, sort, accessors) => {
    const get = sort.key && accessors[sort.key];
    if (!get) return rows;
    const dir = sort.dir === 'desc' ? -1 : 1;
    return rows
        .map((row, i) => [row, i])
        .sort(([a, ai], [b, bi]) => {
            const av = get(a);
            const bv = get(b);
            const aEmpty = av == null || av === '';
            const bEmpty = bv == null || bv === '';
            if (aEmpty && bEmpty) return ai - bi;
            if (aEmpty) return 1;
            if (bEmpty) return -1;
            let cmp;
            if (typeof av === 'number' && typeof bv === 'number') cmp = av - bv;
            else cmp = String(av).localeCompare(String(bv), undefined, { numeric: true });
            return cmp === 0 ? ai - bi : cmp * dir;
        })
        .map(([row]) => row);
};

/** Toggle helper: click the active column to flip direction, else sort it ascending. */
const nextSort = (sort, key) =>
    sort.key === key ? { key, dir: sort.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' };

/** A clickable table header that toggles the table's sort on `sortKey`.
 *  `mono` switches to the dense mono-uppercase column-label styling. */
const SortHeader = ({ label, sortKey, sort, onSort, align = 'left', mono = false }) => {
    const active = sort.key === sortKey;
    const th = mono
        ? 'px-4 py-2.5 font-mono text-[10px] uppercase tracking-wider text-fg-dim'
        : 'px-3 py-2 font-medium';
    return (
        <th className={`${th} ${align === 'right' ? 'text-right' : 'text-left'}`}>
            <button
                type="button"
                onClick={() => onSort(sortKey)}
                aria-label={`Sort by ${label}`}
                className={`inline-flex items-center gap-1 hover:text-fg ${
                    active ? 'text-fg' : ''
                } ${align === 'right' ? 'flex-row-reverse' : ''}`}
            >
                {label}
                <span className="w-2 text-[10px] leading-none">
                    {active ? (sort.dir === 'asc' ? '▲' : '▼') : ''}
                </span>
            </button>
        </th>
    );
};

// Column value-extractors for the unmatched-poster table.
const UNMATCHED_SORT = {
    title: i => i.title,
    type: i => TYPE_LABELS[i._type] || i._type,
    year: i => i.year,
    // Series sort by "how much is missing" (main poster weighted above seasons);
    // movies/collections have no Missing value and sink to the bottom.
    missing: i =>
        i._type === 'series'
            ? (i.missing_main_poster ? 1000 : 0) + (i.missing_seasons?.length || 0)
            : null,
    instance: i => i.instance_name,
};

/** Small artwork placeholder for the title cell — an unmatched item has no
 *  poster cached by definition. */
const UnmatchedThumb = () => (
    <span
        className="shrink-0 w-7 h-10 rounded-[5px] bg-surface-inset border border-border flex items-center justify-center"
        title="No artwork cached"
        aria-hidden="true"
    >
        <span className="material-symbols-outlined text-fg-dim text-[14px]">image</span>
    </span>
);

/** Colour the instance dot by *arr family, matching the mock. */
const instanceDotColor = name => {
    const n = (name || '').toLowerCase();
    if (n.startsWith('sonarr')) return 'var(--color-accent)';
    if (n.startsWith('radarr')) return 'var(--color-success)';
    return 'var(--color-source-cl2k)';
};

/** Gold "missing" chips for the unmatched poster list — a POSTER chip plus a
 *  season-count chip for series. */
const MissingPosterChips = ({ item }) => {
    const chips = [];
    if (item._type === 'series') {
        if (item.missing_main_poster) chips.push('Poster');
        const n = item.missing_seasons?.length || 0;
        if (n) chips.push(`${n} season${n > 1 ? 's' : ''}`);
    }
    if (!chips.length) chips.push('Poster');
    return (
        <span className="flex flex-wrap gap-1.5">
            {chips.map(c => (
                <span
                    key={c}
                    className="inline-flex items-center px-2 py-[3px] rounded-[5px] font-mono text-[9.5px] font-semibold uppercase whitespace-nowrap bg-warning/15 text-warning"
                >
                    {c}
                </span>
            ))}
        </span>
    );
};

/** The single primary external-id label + a tooltip listing every id. */
const externalIdLabel = item =>
    item.tmdb_id
        ? `tmdb ${item.tmdb_id}`
        : item.tvdb_id
          ? `tvdb ${item.tvdb_id}`
          : item.imdb_id
            ? String(item.imdb_id)
            : null;

const externalIdTitle = item =>
    [
        item.tmdb_id && `TMDB ${item.tmdb_id}`,
        item.imdb_id && `IMDB ${item.imdb_id}`,
        item.tvdb_id && `TVDB ${item.tvdb_id}`,
    ]
        .filter(Boolean)
        .join('   ·   ') || undefined;

/** Unified, filterable + searchable table of every unmatched item. */
const UnmatchedList = ({ items, onRefresh, onPick, typeKey: typeKeyProp, onTypeChange }) => {
    const toast = useToast();
    // typeKey can be driven externally (the clickable summary cards) or locally
    // (the All/Movies/Series tabs). Controlled when onTypeChange is provided.
    const [typeKeyLocal, setTypeKeyLocal] = useState('all');
    const typeKey = typeKeyProp ?? typeKeyLocal;
    const setTypeKey = onTypeChange ?? setTypeKeyLocal;
    const [query, setQuery] = useState('');
    const [page, setPage] = useState(0);
    const [busyId, setBusyId] = useState(null);
    const [sort, setSort] = useState({ key: null, dir: 'asc' });
    const onSort = key => {
        setSort(s => nextSort(s, key));
        setPage(0);
    };

    const handleIgnore = async item => {
        setBusyId(item.id);
        try {
            await postersAPI.setMatchIgnored(item.id, {
                kind: item._type === 'collection' ? 'collection' : 'media',
                ignored: true,
            });
            toast.success('Item ignored');
            onRefresh?.();
        } catch {
            toast.error('Failed to ignore item');
        } finally {
            setBusyId(null);
        }
    };

    const all = useMemo(
        () => [
            ...(items.movies || []).map(it => ({ ...it, _type: 'movie' })),
            ...(items.series || []).map(it => ({ ...it, _type: 'series' })),
            ...(items.collections || []).map(it => ({ ...it, _type: 'collection' })),
        ],
        [items]
    );

    const presentTabs = TYPE_TABS.filter(t => t.key === 'all' || all.some(i => i._type === t.key));

    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        return all.filter(
            i =>
                (typeKey === 'all' || i._type === typeKey) &&
                (!q || (i.title || '').toLowerCase().includes(q))
        );
    }, [all, typeKey, query]);

    const sorted = useMemo(() => sortRows(filtered, sort, UNMATCHED_SORT), [filtered, sort]);

    const pageCount = Math.max(1, Math.ceil(sorted.length / UNMATCHED_PAGE_SIZE));
    const safePage = Math.min(page, pageCount - 1);
    const visible = sorted.slice(
        safePage * UNMATCHED_PAGE_SIZE,
        safePage * UNMATCHED_PAGE_SIZE + UNMATCHED_PAGE_SIZE
    );

    const handleCopy = async item => {
        const built = buildPosterRequestText(item, item._type === 'movie' ? 'movie' : 'series');
        if (!built) {
            toast.error('No TMDb/TVDb id available — cannot build a request link');
            return;
        }
        try {
            await copyText(built.text);
            toast.success(
                built.hasTmdb
                    ? 'Poster request copied to clipboard'
                    : 'Copied — TVDb link only; add TMDb link manually before posting'
            );
        } catch {
            toast.error('Clipboard write failed');
        }
    };

    if (all.length === 0) {
        return (
            <p className="text-sm text-fg-muted">
                Nothing unmatched — every tracked item has a poster.
            </p>
        );
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3 flex-wrap">
                <div className="inline-flex items-center h-10 p-1 gap-0.5 bg-surface border border-border rounded-lg">
                    {presentTabs.map(t => (
                        <button
                            key={t.key}
                            onClick={() => {
                                setTypeKey(t.key);
                                setPage(0);
                            }}
                            className={`h-8 px-3 rounded-[7px] text-[12.5px] font-semibold transition-colors ${
                                typeKey === t.key
                                    ? 'bg-primary text-on-color'
                                    : 'text-fg-muted hover:text-fg'
                            }`}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>
                <span className="font-mono text-[11px] px-2 py-0.5 rounded-full bg-warning/15 text-warning">
                    {filtered.length}
                </span>
                <div className="flex-1 min-w-[14rem] flex items-center gap-2 h-10 px-3 rounded-lg bg-surface border border-border focus-within:border-primary transition-colors">
                    <span
                        className="material-symbols-outlined text-fg-subtle text-[16px] shrink-0"
                        aria-hidden="true"
                    >
                        search
                    </span>
                    <input
                        type="text"
                        value={query}
                        onChange={e => {
                            setQuery(e.target.value);
                            setPage(0);
                        }}
                        placeholder="Search unmatched…"
                        aria-label="Search unmatched titles"
                        className="flex-1 min-w-0 bg-transparent border-0 outline-none text-sm text-fg placeholder:text-fg-dim"
                    />
                </div>
            </div>
            {filtered.length === 0 ? (
                <p className="text-sm text-fg-subtle">No matches.</p>
            ) : (
                <section
                    className="bg-surface border border-border rounded-xl overflow-hidden"
                    style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
                >
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-border">
                                    <SortHeader
                                        label="Title"
                                        sortKey="title"
                                        sort={sort}
                                        onSort={onSort}
                                        mono
                                    />
                                    <SortHeader
                                        label="Type"
                                        sortKey="type"
                                        sort={sort}
                                        onSort={onSort}
                                        mono
                                    />
                                    <SortHeader
                                        label="Instance"
                                        sortKey="instance"
                                        sort={sort}
                                        onSort={onSort}
                                        mono
                                    />
                                    <SortHeader
                                        label="Missing"
                                        sortKey="missing"
                                        sort={sort}
                                        onSort={onSort}
                                        mono
                                    />
                                    <th className="px-4 py-2.5 text-left font-mono text-[10px] uppercase tracking-wider text-fg-dim">
                                        External ID
                                    </th>
                                    <th className="px-4 py-2.5 text-right font-mono text-[10px] uppercase tracking-wider text-fg-dim">
                                        Action
                                    </th>
                                </tr>
                            </thead>
                            <tbody>
                                {visible.map((item, idx) => {
                                    const action = rowActionFor?.(item);
                                    const extId = externalIdLabel(item);
                                    return (
                                        <tr
                                            key={`${item._type}-${item.tmdb_id || item.tvdb_id || item.title || idx}`}
                                            className="border-b border-border-light last:border-0 hover:bg-row-hover transition-colors"
                                        >
                                            <td className="px-4 py-2.5">
                                                <div className="flex items-center gap-3 min-w-0">
                                                    <UnmatchedThumb />
                                                    <div className="min-w-0">
                                                        <div className="font-semibold text-sm text-fg truncate">
                                                            {item._type !== 'collection' ? (
                                                                <Link
                                                                    to={`/poster/search/assets?q=${encodeURIComponent(item.title)}`}
                                                                    className="hover:text-accent hover:underline"
                                                                    title="Search synced posters for this title"
                                                                >
                                                                    {item.title}
                                                                </Link>
                                                            ) : (
                                                                item.title
                                                            )}
                                                        </div>
                                                        <div className="font-mono text-[10px] text-fg-subtle mt-0.5">
                                                            {item.year || '—'}
                                                        </div>
                                                    </div>
                                                </div>
                                            </td>
                                            <td className="px-4 py-2.5 font-mono text-[11px] uppercase text-fg-data">
                                                {TYPE_LABELS[item._type]}
                                            </td>
                                            <td className="px-4 py-2.5">
                                                <span className="flex items-center gap-2 min-w-0 font-mono text-[11px] text-fg-muted">
                                                    <span
                                                        className="shrink-0 w-1.5 h-1.5 rounded-full"
                                                        style={{
                                                            background: instanceDotColor(
                                                                item.instance_name
                                                            ),
                                                        }}
                                                    />
                                                    <span className="truncate">
                                                        {item.instance_name || '—'}
                                                    </span>
                                                </span>
                                            </td>
                                            <td className="px-4 py-2.5">
                                                <MissingPosterChips item={item} />
                                            </td>
                                            <td
                                                className="px-4 py-2.5 font-mono text-[12px] text-accent whitespace-nowrap"
                                                title={externalIdTitle(item)}
                                            >
                                                {extId || '—'}
                                            </td>
                                            <td className="px-4 py-2.5">
                                                <div className="flex items-center gap-2 justify-end">
                                                    {action && (
                                                        <Link
                                                            to={action.to}
                                                            className="inline-flex items-center justify-center w-8 h-8 rounded-[7px] text-fg-subtle hover:text-accent hover:bg-surface-inset"
                                                            aria-label={action.ariaLabel}
                                                            title={action.title}
                                                        >
                                                            <span className="material-symbols-outlined text-[18px]">
                                                                {action.icon}
                                                            </span>
                                                        </Link>
                                                    )}
                                                    {item._type !== 'collection' && (
                                                        <button
                                                            type="button"
                                                            onClick={() => handleCopy(item)}
                                                            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-[7px] bg-primary text-on-color text-xs font-semibold hover:brightness-110 transition"
                                                            title="Copy a poster request to the clipboard"
                                                        >
                                                            <span className="material-symbols-outlined text-[14px]">
                                                                send
                                                            </span>
                                                            Request
                                                        </button>
                                                    )}
                                                    <button
                                                        type="button"
                                                        onClick={() => onPick?.(item)}
                                                        className="inline-flex items-center h-8 px-3 rounded-[7px] bg-surface-inset border border-border text-fg-muted text-xs font-semibold hover:bg-row-hover hover:text-fg transition"
                                                        title="Pick a poster to apply now"
                                                    >
                                                        Match
                                                    </button>
                                                    {item.id != null && (
                                                        <IconButton
                                                            icon="block"
                                                            size="small"
                                                            variant="ghost"
                                                            disabled={busyId === item.id}
                                                            aria-label="Ignore this item"
                                                            title="Ignore — stop showing this item"
                                                            onClick={() => handleIgnore(item)}
                                                        />
                                                    )}
                                                </div>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </section>
            )}
            {filtered.length > 0 && pageCount > 1 && (
                <div className="flex items-center justify-center gap-3 text-sm text-fg-muted">
                    <IconButton
                        icon="chevron_left"
                        variant="ghost"
                        aria-label="Previous page"
                        disabled={safePage === 0}
                        onClick={() => setPage(p => Math.max(0, p - 1))}
                    />
                    <span>
                        Page {safePage + 1} / {pageCount} ({filtered.length} items)
                    </span>
                    <IconButton
                        icon="chevron_right"
                        variant="ghost"
                        aria-label="Next page"
                        disabled={safePage >= pageCount - 1}
                        onClick={() => setPage(p => Math.min(pageCount - 1, p + 1))}
                    />
                </div>
            )}

            <div className="flex items-center gap-3 px-4 py-3 rounded-xl border border-dashed border-border">
                <span
                    className="material-symbols-outlined text-fg-subtle text-[18px] shrink-0"
                    aria-hidden="true"
                >
                    info
                </span>
                <span className="text-[12.5px] text-fg-subtle">
                    Matched artwork can come from <span className="text-accent">GDrive</span>,{' '}
                    <span className="text-success">local assets</span>, or be built in{' '}
                    <span className="text-source-cl2k">CL2K</span> /{' '}
                    <span className="text-warning">MM2K</span> — every match records the source
                    style and the user it came from.
                </span>
            </div>
        </div>
    );
};

const STATUS_VIEWS = [
    { key: 'unmatched', label: 'Unmatched' },
    { key: 'review', label: 'Needs Review' },
    { key: 'locked', label: 'Locked' },
    { key: 'ignored', label: 'Ignored' },
];

/** Colour for a 0–1 confidence score. */
const confidenceTone = c => {
    if (c == null) return 'text-fg-subtle';
    if (c >= 0.9) return 'text-success';
    if (c >= 0.7) return 'text-warning';
    return 'text-error';
};

const kindOf = row => (row.asset_type === 'collection' ? 'collection' : 'media');

// Column value-extractors for the review / locked / ignored poster table.
const REVIEW_SORT = {
    title: r => r.title,
    type: r => TYPE_LABELS[r.type] || TYPE_LABELS[r.asset_type] || r.type,
    year: r => r.year,
    instance: r => r.instance_name,
    confidence: r => r.match_confidence,
};

/**
 * Flat table for the Needs-Review and Ignored tabs. Shows the match
 * confidence + reason the backend now records, plus per-row actions:
 * review → Approve / Ignore, ignored → Restore.
 */
const MatchReviewList = ({ rows, mode, onRefresh, onPick }) => {
    const toast = useToast();
    const [query, setQuery] = useState('');
    const [busyId, setBusyId] = useState(null);
    const [sort, setSort] = useState({ key: null, dir: 'asc' });
    const onSort = key => setSort(s => nextSort(s, key));

    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        return rows.filter(r => !q || (r.title || '').toLowerCase().includes(q));
    }, [rows, query]);

    const sorted = useMemo(() => sortRows(filtered, sort, REVIEW_SORT), [filtered, sort]);

    const act = async (fn, row, successMsg) => {
        setBusyId(row.id);
        try {
            await fn();
            toast.success(successMsg);
            onRefresh();
        } catch {
            toast.error('Action failed');
        } finally {
            setBusyId(null);
        }
    };

    if (rows.length === 0) {
        let emptyMsg;
        if (mode === 'review') {
            emptyMsg = 'Nothing to review — every match is confident.';
        } else if (mode === 'locked') {
            emptyMsg =
                'No locked items. Approving a match or applying a poster manually locks it here.';
        } else {
            emptyMsg =
                'No ignored items. Dismiss a row from Unmatched or Needs Review to park it here.';
        }
        return <p className="text-sm text-fg-muted">{emptyMsg}</p>;
    }

    return (
        <div className="flex flex-col gap-3">
            <input
                type="text"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search title…"
                aria-label="Search titles"
                className="px-3 py-2 bg-input border border-border rounded-md text-fg text-sm self-start"
                style={{ minWidth: '14rem' }}
            />
            {filtered.length === 0 ? (
                <p className="text-sm text-fg-subtle">No matches.</p>
            ) : (
                <div className="overflow-x-auto rounded-lg border border-border">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="bg-surface-alt text-fg-muted text-left">
                                <SortHeader
                                    label="Title"
                                    sortKey="title"
                                    sort={sort}
                                    onSort={onSort}
                                />
                                <SortHeader
                                    label="Type"
                                    sortKey="type"
                                    sort={sort}
                                    onSort={onSort}
                                />
                                <SortHeader
                                    label="Year"
                                    sortKey="year"
                                    sort={sort}
                                    onSort={onSort}
                                />
                                <SortHeader
                                    label="Instance"
                                    sortKey="instance"
                                    sort={sort}
                                    onSort={onSort}
                                />
                                <SortHeader
                                    label="Confidence"
                                    sortKey="confidence"
                                    sort={sort}
                                    onSort={onSort}
                                />
                                <th className="px-3 py-2 font-medium">Why</th>
                                <th className="px-3 py-2 font-medium text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                            {sorted.map((item, idx) => (
                                <tr
                                    key={`${item.id ?? idx}`}
                                    className="bg-surface hover:bg-surface-alt align-top"
                                >
                                    <td className="px-3 py-2 text-fg">
                                        <Link
                                            to={`/poster/search/assets?q=${encodeURIComponent(item.title || '')}`}
                                            className="hover:text-accent hover:underline"
                                            title="Search synced posters for this title"
                                        >
                                            {item.title}
                                        </Link>
                                    </td>
                                    <td className="px-3 py-2 text-fg-muted">
                                        {TYPE_LABELS[item.type] ||
                                            TYPE_LABELS[item.asset_type] ||
                                            item.type ||
                                            '—'}
                                    </td>
                                    <td className="px-3 py-2 text-fg-muted">{item.year || '—'}</td>
                                    <td className="px-3 py-2 text-fg-muted">
                                        {item.instance_name || '—'}
                                    </td>
                                    <td className="px-3 py-2">
                                        {item.match_confidence != null ? (
                                            <span
                                                className={`font-semibold ${confidenceTone(item.match_confidence)}`}
                                            >
                                                {Math.round(item.match_confidence * 100)}%
                                            </span>
                                        ) : (
                                            <span className="text-fg-subtle">—</span>
                                        )}
                                    </td>
                                    <td className="px-3 py-2 text-fg-muted max-w-md">
                                        <span>{item.match_reason || '—'}</span>
                                        {item.conflicts?.length > 1 && (
                                            <span className="block text-xs text-warning mt-1">
                                                {item.conflicts.length} competing posters
                                            </span>
                                        )}
                                    </td>
                                    <td className="px-3 py-2 text-right whitespace-nowrap">
                                        {mode === 'review' ? (
                                            <>
                                                <IconButton
                                                    icon="wallpaper"
                                                    size="small"
                                                    variant="ghost"
                                                    aria-label="Choose a poster"
                                                    title="Choose a poster to apply"
                                                    onClick={() => onPick?.(item)}
                                                />
                                                <IconButton
                                                    icon="check_circle"
                                                    size="small"
                                                    variant="ghost"
                                                    disabled={busyId === item.id}
                                                    aria-label="Approve match"
                                                    title="Approve — mark as confidently matched"
                                                    onClick={() =>
                                                        act(
                                                            () =>
                                                                postersAPI.approveMatch(item.id, {
                                                                    kind: kindOf(item),
                                                                }),
                                                            item,
                                                            'Match approved'
                                                        )
                                                    }
                                                />
                                                <IconButton
                                                    icon="block"
                                                    size="small"
                                                    variant="ghost"
                                                    disabled={busyId === item.id}
                                                    aria-label="Ignore"
                                                    title="Ignore — hide from these lists"
                                                    onClick={() =>
                                                        act(
                                                            () =>
                                                                postersAPI.setMatchIgnored(
                                                                    item.id,
                                                                    {
                                                                        kind: kindOf(item),
                                                                        ignored: true,
                                                                    }
                                                                ),
                                                            item,
                                                            'Item ignored'
                                                        )
                                                    }
                                                />
                                            </>
                                        ) : mode === 'locked' ? (
                                            <IconButton
                                                icon="lock_open"
                                                size="small"
                                                variant="ghost"
                                                disabled={busyId === item.id}
                                                aria-label="Unlock"
                                                title="Unlock — re-open for review so the matcher can recompute it"
                                                onClick={() =>
                                                    act(
                                                        () =>
                                                            postersAPI.unlockMatch(item.id, {
                                                                kind: kindOf(item),
                                                            }),
                                                        item,
                                                        'Match unlocked'
                                                    )
                                                }
                                            />
                                        ) : (
                                            <IconButton
                                                icon="undo"
                                                size="small"
                                                variant="ghost"
                                                disabled={busyId === item.id}
                                                aria-label="Restore"
                                                title="Restore — return to its normal list"
                                                onClick={() =>
                                                    act(
                                                        () =>
                                                            postersAPI.setMatchIgnored(item.id, {
                                                                kind: kindOf(item),
                                                                ignored: false,
                                                            }),
                                                        item,
                                                        'Item restored'
                                                    )
                                                }
                                            />
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};

/**
 * "Additional artwork" view: per-type coverage cards (logo/background/square
 * art) styled like the poster summary cards, plus a per-item table of media
 * still missing the selected artwork type. Per-item actions: copy a request,
 * ignore (per-type, "not needed"), and a link to the Asset Renamerr module.
 */
const ARTWORK_PAGE_SIZE = 50;
// Which per-media list each status tab reads, and which type-array on a row
// carries the artwork types relevant to that tab.
const ARTWORK_STATUS = {
    unmatched: { listKey: 'unmatched', typesKey: 'missing' },
    review: { listKey: 'needs_review', typesKey: 'failed' },
    locked: { listKey: 'locked', typesKey: 'locked' },
    ignored: { listKey: 'ignored', typesKey: 'ignored_types' },
};

// Subtle checkerboard so a transparent logo/squareart thumbnail reads as
// transparent (not a flat dark block) in the picker — mirrors the Asset Search
// page's artwork rendering.
const ARTWORK_TRANSPARENCY_BG = {
    backgroundImage:
        'linear-gradient(45deg, var(--color-surface-alt) 25%, transparent 25%), ' +
        'linear-gradient(-45deg, var(--color-surface-alt) 25%, transparent 25%), ' +
        'linear-gradient(45deg, transparent 75%, var(--color-surface-alt) 75%), ' +
        'linear-gradient(-45deg, transparent 75%, var(--color-surface-alt) 75%)',
    backgroundSize: '16px 16px',
    backgroundPosition: '0 0, 0 8px, 8px -8px, -8px 0px',
};

/** Chip listing the artwork type(s) a media row is missing/failed/ignored. */
const MISSING_CHIP_COLOR = key => {
    if (key === 'poster') return 'bg-warning/15 text-warning';
    if (key === 'background') return 'bg-accent/12 text-accent';
    return 'bg-surface-inset text-fg-data';
};

const MissingChips = ({ typeKeys, reasons }) => {
    if (!typeKeys?.length) return <span className="text-fg-subtle">—</span>;
    return (
        <span className="flex flex-wrap gap-1.5">
            {typeKeys.map(tk => {
                const meta = ARTWORK_TYPES.find(a => a.key === tk);
                const reason = reasons?.[tk];
                return (
                    <span
                        key={tk}
                        title={reason || undefined}
                        className={`inline-flex items-center px-2 py-[3px] rounded-[5px] font-mono text-[9.5px] font-semibold uppercase whitespace-nowrap ${MISSING_CHIP_COLOR(tk)}`}
                    >
                        {meta?.label || tk}
                    </span>
                );
            })}
        </span>
    );
};

const ArtworkView = ({ data, status, isLoading, onRefresh, onPick }) => {
    const toast = useToast();
    // Artwork-type card filter: null = all types; otherwise restrict rows to
    // ones whose relevant type-array includes this artwork type.
    const [typeFilter, setTypeFilter] = useState(null);
    // Media-type tab (All / Movies / Series), mirroring the poster list.
    const [mediaTypeKey, setMediaTypeKey] = useState('all');
    const [query, setQuery] = useState('');
    const [page, setPage] = useState(0);
    const [busyKey, setBusyKey] = useState(null);
    const [sort, setSort] = useState({ key: null, dir: 'asc' });
    const onSort = key => {
        setSort(s => nextSort(s, key));
        setPage(0);
    };

    const types = useMemo(() => data?.data?.types || {}, [data]);
    const media = useMemo(() => data?.data?.media || {}, [data]);

    const cfg = ARTWORK_STATUS[status] || ARTWORK_STATUS.unmatched;
    const baseRows = useMemo(() => media[cfg.listKey] || [], [media, cfg.listKey]);

    // Only show media-type tabs that are actually present in the current list.
    const mediaTabs = useMemo(() => {
        const tabs = [{ key: 'all', label: 'All' }];
        if (baseRows.some(r => r.asset_type === 'movie'))
            tabs.push({ key: 'movie', label: 'Movies' });
        if (baseRows.some(r => r.asset_type === 'show'))
            tabs.push({ key: 'show', label: 'Series' });
        return tabs;
    }, [baseRows]);

    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        return baseRows.filter(
            r =>
                (mediaTypeKey === 'all' || r.asset_type === mediaTypeKey) &&
                (!typeFilter || (r[cfg.typesKey] || []).includes(typeFilter)) &&
                (!q || (r.title || '').toLowerCase().includes(q))
        );
    }, [baseRows, mediaTypeKey, typeFilter, cfg.typesKey, query]);

    // Column value-extractors. Type mirrors the rendered label; the dynamic
    // missing/failed/not-needed column sorts by how many artwork types apply.
    const accessors = useMemo(
        () => ({
            title: r => r.title,
            type: r =>
                r.asset_type === 'show'
                    ? r.season_number != null
                        ? 'Season'
                        : 'Series'
                    : TYPE_LABELS[r.asset_type] || r.asset_type,
            year: r => r.year,
            missing: r => (r[cfg.typesKey] || []).length,
            instance: r => r.instance_name,
        }),
        [cfg.typesKey]
    );

    const sorted = useMemo(() => sortRows(filtered, sort, accessors), [filtered, sort, accessors]);

    // Reset to page 0 whenever the result set changes underneath us.
    const pageCount = Math.max(1, Math.ceil(sorted.length / ARTWORK_PAGE_SIZE));
    const safePage = Math.min(page, pageCount - 1);
    const visible = sorted.slice(
        safePage * ARTWORK_PAGE_SIZE,
        safePage * ARTWORK_PAGE_SIZE + ARTWORK_PAGE_SIZE
    );

    const copyRequest = async item => {
        const type = item.asset_type === 'movie' ? 'movie' : 'series';
        const built = buildPosterRequestText(item, type);
        if (!built) {
            toast.error('No external ID to build a request');
            return;
        }
        const ok = await copyText(built.text);
        toast[ok ? 'success' : 'error'](ok ? 'Request copied' : 'Copy failed');
    };

    // Ignore / restore every artwork type currently shown for this row (the
    // ones in its relevant type-array), so the per-media row acts as a unit.
    const setIgnored = async (item, ignored) => {
        const targetTypes = item[cfg.typesKey] || [];
        if (!targetTypes.length) return;
        setBusyKey(item.id);
        try {
            await Promise.all(
                targetTypes.map(tk =>
                    postersAPI.ignoreArtwork(item.id, tk, {
                        kind: item.asset_type === 'collection' ? 'collection' : 'media',
                        ignored,
                    })
                )
            );
            toast.success(ignored ? 'Marked not needed' : 'Restored');
            onRefresh();
        } catch {
            toast.error('Action failed');
        } finally {
            setBusyKey(null);
        }
    };

    // Unlock every locked artwork type on this row so the matcher is free to
    // re-resolve it on the next run (the per-type counterpart of poster unlock).
    const unlockRow = async item => {
        const targetTypes = item.locked || [];
        if (!targetTypes.length) return;
        setBusyKey(item.id);
        try {
            await Promise.all(
                targetTypes.map(tk =>
                    postersAPI.unlockArtwork(item.id, tk, {
                        kind: item.asset_type === 'collection' ? 'collection' : 'media',
                    })
                )
            );
            toast.success('Unlocked — the matcher will re-resolve it on the next run');
            onRefresh();
        } catch {
            toast.error('Failed to unlock');
        } finally {
            setBusyKey(null);
        }
    };

    if (isLoading) return <Spinner size="large" text="Loading artwork coverage..." center />;

    const isIgnoredTab = status === 'ignored';
    const isReviewTab = status === 'review';
    const isLockedTab = status === 'locked';
    const missingColLabel = isIgnoredTab
        ? 'Not needed'
        : isReviewTab
          ? 'Failed'
          : isLockedTab
            ? 'Locked'
            : 'Missing';

    return (
        <div className="flex flex-col gap-4">
            {/* Per-type coverage cards — also act as a filter on the per-media list */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {/* Only render cards for types present in the response — a
                    deselected asset type (e.g. squareart) is omitted entirely. */}
                {ARTWORK_TYPES.filter(({ key }) => types[key]).map(({ key, label, icon }) => {
                    const t = types[key] || {};
                    const isActive = typeFilter === key;
                    return (
                        <button
                            key={key}
                            type="button"
                            onClick={() => {
                                setTypeFilter(isActive ? null : key);
                                setPage(0);
                            }}
                            title={
                                isActive
                                    ? 'Showing only items missing this — click to clear'
                                    : 'Filter the list to items missing this'
                            }
                            className={`text-left p-4 rounded-lg border transition-colors ${
                                isActive
                                    ? 'bg-surface border-primary ring-1 ring-primary/40'
                                    : 'bg-surface border-border hover:border-primary/50'
                            }`}
                        >
                            <p className="text-sm text-fg-muted flex items-center gap-1.5">
                                <span className="text-base leading-none">{icon}</span>
                                {label}
                            </p>
                            <p className="text-2xl font-bold text-warning">{t.missing ?? 0}</p>
                            <p className="text-xs text-fg-subtle mt-1">
                                of {t.total || 0} total &mdash;{' '}
                                {t.percent_complete?.toFixed(1) || 0}% complete
                            </p>
                            {t.total > 0 && (
                                <div className="mt-2 h-2 bg-surface-alt rounded-full overflow-hidden">
                                    <div
                                        className="h-full bg-success rounded-full"
                                        style={{ width: `${t.percent_complete || 0}%` }}
                                    />
                                </div>
                            )}
                        </button>
                    );
                })}
            </div>

            <div className="flex items-center gap-3 flex-wrap">
                <div className="inline-flex items-center h-10 p-1 gap-0.5 bg-surface border border-border rounded-lg">
                    {mediaTabs.map(t => (
                        <button
                            key={t.key}
                            onClick={() => {
                                setMediaTypeKey(t.key);
                                setPage(0);
                            }}
                            className={`h-8 px-3 rounded-[7px] text-[12.5px] font-semibold transition-colors ${
                                mediaTypeKey === t.key
                                    ? 'bg-primary text-on-color'
                                    : 'text-fg-muted hover:text-fg'
                            }`}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>
                <span className="font-mono text-[11px] px-2 py-0.5 rounded-full bg-warning/15 text-warning">
                    {filtered.length}
                </span>
                {typeFilter && (
                    <button
                        type="button"
                        onClick={() => setTypeFilter(null)}
                        className="text-xs text-fg-muted hover:text-fg underline"
                    >
                        Clear {ARTWORK_TYPES.find(a => a.key === typeFilter)?.label} filter
                    </button>
                )}
                <div className="flex-1 min-w-[14rem] flex items-center gap-2 h-10 px-3 rounded-lg bg-surface border border-border focus-within:border-primary transition-colors">
                    <span
                        className="material-symbols-outlined text-fg-subtle text-[16px] shrink-0"
                        aria-hidden="true"
                    >
                        search
                    </span>
                    <input
                        type="text"
                        value={query}
                        onChange={e => {
                            setQuery(e.target.value);
                            setPage(0);
                        }}
                        placeholder="Search title…"
                        aria-label="Search titles"
                        className="flex-1 min-w-0 bg-transparent border-0 outline-none text-sm text-fg placeholder:text-fg-dim"
                    />
                </div>
            </div>

            {filtered.length === 0 ? (
                <p className="text-sm text-fg-muted">
                    {isIgnoredTab
                        ? 'Nothing marked “not needed”.'
                        : status === 'review'
                          ? 'Nothing to review — no failed artwork applies.'
                          : 'No media missing additional artwork.'}
                </p>
            ) : (
                <>
                    <section
                        className="bg-surface border border-border rounded-xl overflow-hidden"
                        style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
                    >
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="border-b border-border">
                                        <SortHeader
                                            label="Title"
                                            sortKey="title"
                                            sort={sort}
                                            onSort={onSort}
                                            mono
                                        />
                                        <SortHeader
                                            label="Type"
                                            sortKey="type"
                                            sort={sort}
                                            onSort={onSort}
                                            mono
                                        />
                                        <SortHeader
                                            label="Year"
                                            sortKey="year"
                                            sort={sort}
                                            onSort={onSort}
                                            mono
                                        />
                                        <SortHeader
                                            label={missingColLabel}
                                            sortKey="missing"
                                            sort={sort}
                                            onSort={onSort}
                                            mono
                                        />
                                        {isReviewTab && (
                                            <th className="px-4 py-2.5 text-left font-mono text-[10px] uppercase tracking-wider text-fg-dim">
                                                Why
                                            </th>
                                        )}
                                        <SortHeader
                                            label="Instance"
                                            sortKey="instance"
                                            sort={sort}
                                            onSort={onSort}
                                            mono
                                        />
                                        <th className="px-4 py-2.5 text-left font-mono text-[10px] uppercase tracking-wider text-fg-dim">
                                            TMDB
                                        </th>
                                        <th className="px-4 py-2.5 text-left font-mono text-[10px] uppercase tracking-wider text-fg-dim">
                                            IMDB
                                        </th>
                                        <th className="px-4 py-2.5 text-left font-mono text-[10px] uppercase tracking-wider text-fg-dim">
                                            TVDB
                                        </th>
                                        <th className="px-4 py-2.5 text-right font-mono text-[10px] uppercase tracking-wider text-fg-dim">
                                            Actions
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {visible.map((item, idx) => (
                                        <tr
                                            key={`${item.id ?? idx}`}
                                            className="border-b border-border-light last:border-0 hover:bg-row-hover transition-colors align-top"
                                        >
                                            <td className="px-4 py-2.5 text-fg">
                                                <Link
                                                    to={`/poster/search/assets?q=${encodeURIComponent(item.title || '')}&image_type=${typeFilter || 'artwork'}`}
                                                    className="hover:text-accent hover:underline"
                                                    title="Search synced assets for this title"
                                                >
                                                    {item.title}
                                                </Link>
                                                {item.season_number != null && (
                                                    <span className="ml-2 text-xs text-fg-subtle">
                                                        {item.season_number === 0
                                                            ? 'Specials'
                                                            : `S${String(item.season_number).padStart(2, '0')}`}
                                                    </span>
                                                )}
                                            </td>
                                            <td className="px-4 py-2.5 text-fg-muted">
                                                {item.asset_type === 'show'
                                                    ? item.season_number != null
                                                        ? 'Season'
                                                        : 'Series'
                                                    : TYPE_LABELS[item.asset_type] ||
                                                      item.asset_type ||
                                                      '—'}
                                            </td>
                                            <td className="px-4 py-2.5 text-fg-muted">
                                                {item.year || '—'}
                                            </td>
                                            <td className="px-4 py-2.5">
                                                <MissingChips
                                                    typeKeys={item[cfg.typesKey]}
                                                    reasons={item.reasons}
                                                />
                                            </td>
                                            {isReviewTab && (
                                                <td className="px-4 py-2.5 text-fg-muted max-w-xs">
                                                    {(() => {
                                                        const reasons = item.reasons || {};
                                                        const uniq = [
                                                            ...new Set(
                                                                (item.failed || [])
                                                                    .map(t => reasons[t])
                                                                    .filter(Boolean)
                                                            ),
                                                        ];
                                                        return uniq.length ? (
                                                            <span title={uniq.join(' • ')}>
                                                                {uniq.join('; ')}
                                                            </span>
                                                        ) : (
                                                            <span className="text-fg-subtle">
                                                                No detail recorded
                                                            </span>
                                                        );
                                                    })()}
                                                </td>
                                            )}
                                            <td className="px-4 py-2.5 text-fg-muted">
                                                {item.instance_name || '—'}
                                            </td>
                                            <td className="px-4 py-2.5 text-fg-subtle font-mono text-xs">
                                                {formatId(item.tmdb_id) || '—'}
                                            </td>
                                            <td className="px-4 py-2.5 text-fg-subtle font-mono text-xs">
                                                {formatId(item.imdb_id) || '—'}
                                            </td>
                                            <td className="px-4 py-2.5 text-fg-subtle font-mono text-xs">
                                                {formatId(item.tvdb_id) || '—'}
                                            </td>
                                            <td className="px-4 py-2.5 text-right whitespace-nowrap">
                                                {!isIgnoredTab && (
                                                    <IconButton
                                                        icon="wallpaper"
                                                        size="small"
                                                        variant="ghost"
                                                        aria-label="Choose artwork"
                                                        title={
                                                            isLockedTab
                                                                ? 'Re-pick — choose a different artwork file'
                                                                : 'Choose an artwork file to apply'
                                                        }
                                                        onClick={() =>
                                                            onPick?.(item, item[cfg.typesKey] || [])
                                                        }
                                                    />
                                                )}
                                                <IconButton
                                                    icon="content_copy"
                                                    size="small"
                                                    variant="ghost"
                                                    aria-label="Copy request"
                                                    title="Copy a request for this artwork"
                                                    onClick={() => copyRequest(item)}
                                                />
                                                {isIgnoredTab ? (
                                                    <IconButton
                                                        icon="undo"
                                                        size="small"
                                                        variant="ghost"
                                                        disabled={busyKey === item.id}
                                                        aria-label="Restore"
                                                        title="Restore — track this artwork again"
                                                        onClick={() => setIgnored(item, false)}
                                                    />
                                                ) : isLockedTab ? (
                                                    <IconButton
                                                        icon="lock_open"
                                                        size="small"
                                                        variant="ghost"
                                                        disabled={busyKey === item.id}
                                                        aria-label="Unlock"
                                                        title="Unlock — let the matcher re-resolve this artwork on the next run"
                                                        onClick={() => unlockRow(item)}
                                                    />
                                                ) : (
                                                    <IconButton
                                                        icon="block"
                                                        size="small"
                                                        variant="ghost"
                                                        disabled={busyKey === item.id}
                                                        aria-label="Not needed"
                                                        title="Not needed — stop tracking the missing artwork for this item"
                                                        onClick={() => setIgnored(item, true)}
                                                    />
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </section>

                    {pageCount > 1 && (
                        <div className="flex items-center justify-center gap-3 text-sm text-fg-muted">
                            <IconButton
                                icon="chevron_left"
                                variant="ghost"
                                aria-label="Previous page"
                                disabled={safePage === 0}
                                onClick={() => setPage(p => Math.max(0, p - 1))}
                            />
                            <span>
                                Page {safePage + 1} / {pageCount} ({filtered.length} items)
                            </span>
                            <IconButton
                                icon="chevron_right"
                                variant="ghost"
                                aria-label="Next page"
                                disabled={safePage >= pageCount - 1}
                                onClick={() => setPage(p => Math.min(pageCount - 1, p + 1))}
                            />
                        </div>
                    )}
                </>
            )}
        </div>
    );
};

/** One selectable poster thumbnail in the picker. */
const PickerThumb = ({ cand, busy, onApply }) => {
    const [failed, setFailed] = useState(false);
    return (
        <button
            type="button"
            disabled={busy}
            onClick={() => onApply(cand.poster_id)}
            title={cand.would_match ? 'Would match' : cand.reason}
            className={`group relative rounded-lg overflow-hidden border text-left ${
                cand.would_match ? 'border-success/60' : 'border-border'
            } hover:border-brand-primary disabled:opacity-50`}
        >
            <div
                className="bg-input flex items-center justify-center"
                style={{ aspectRatio: '2 / 3' }}
            >
                {failed ? (
                    <span className="material-symbols-outlined text-fg-subtle text-3xl">
                        broken_image
                    </span>
                ) : (
                    <img
                        src={postersAPI.getThumbnailUrl(cand.poster_id, 200)}
                        alt={cand.title || `#${cand.poster_id}`}
                        loading="lazy"
                        className="object-cover w-full h-full"
                        onError={() => setFailed(true)}
                    />
                )}
            </div>
            <div className="px-2 py-1">
                <p className="text-xs text-fg-muted truncate">{cand.style || cand.owner || '—'}</p>
                {cand.season_number != null && (
                    <p className="text-[10px] text-fg-subtle">Season {cand.season_number}</p>
                )}
            </div>
            <span className="absolute inset-0 flex items-center justify-center bg-primary/80 opacity-0 group-hover:opacity-100 transition-opacity">
                <span className="material-symbols-outlined text-white">check</span>
            </span>
        </button>
    );
};

/** Modal that fetches candidate posters for a media row and applies the chosen one. */
const PosterPickerModal = ({ item, onClose, onApplied }) => {
    const toast = useToast();
    const kind = item.asset_type === 'collection' ? 'collection' : 'media';
    const [candidates, setCandidates] = useState(null);
    const [busy, setBusy] = useState(null);

    useEffect(() => {
        let alive = true;
        postersAPI
            .fetchMatchCandidates(item.id, { kind })
            .then(r => alive && setCandidates(r?.data?.candidates || []))
            .catch(() => alive && setCandidates([]));
        return () => {
            alive = false;
        };
    }, [item.id, kind]);

    const apply = async posterId => {
        setBusy(posterId);
        try {
            const res = await postersAPI.applyMatch(item.id, posterId, { kind });
            // Prefer the backend's precise outcome ("Poster applied to Plex" /
            // "Poster copied to assets directory (Kometa will apply)") so the
            // user sees which Apply Method path ran; fall back to a generic msg.
            toast.success(
                res?.message ||
                    (res?.data?.applied
                        ? 'Poster applied'
                        : 'Match recorded — applies on the next poster_renamerr run')
            );
            onApplied?.();
            onClose();
        } catch {
            toast.error('Failed to apply poster');
            setBusy(null);
        }
    };

    return (
        <Modal isOpen onClose={onClose} size="large">
            <Modal.Header>
                Choose a poster — {item.title}
                {item.year ? ` (${item.year})` : ''}
                {item.season_number != null ? ` · Season ${item.season_number}` : ''}
            </Modal.Header>
            <Modal.Body>
                <p className="text-xs text-fg-subtle mb-3">
                    Applying follows Poster Renamerr&apos;s <strong>Apply Method</strong>: with{' '}
                    <strong>Plex</strong> the poster is uploaded straight to Plex (for instances
                    you&apos;ve opted in); with <strong>Kometa</strong> it&apos;s copied into your
                    assets directory for Kometa to apply. The match is saved &amp; locked either
                    way.
                </p>
                {candidates === null ? (
                    <p className="text-sm text-fg-muted">Searching for posters…</p>
                ) : candidates.length === 0 ? (
                    <p className="text-sm text-fg-muted">
                        No candidate posters found in your cache for this title. The asset may not
                        exist in any synced source.
                    </p>
                ) : (
                    <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-3">
                        {candidates.map(c => (
                            <PickerThumb
                                key={c.poster_id}
                                cand={c}
                                busy={busy != null}
                                onApply={apply}
                            />
                        ))}
                    </div>
                )}
            </Modal.Body>
        </Modal>
    );
};

/**
 * Destructive "Reset" control for the active class. Resets CHUB's match
 * tracking to all-missing (posters: matched flag + metadata; artwork: applied
 * provenance) so the next module run repopulates it. Preserves user-curated
 * state (ignored / locked) and never deletes posters from disk or Plex.
 */
/** Candidate thumbnail for the artwork picker — object-contain on a
 *  transparency checkerboard so wide/transparent logos read correctly (the
 *  artwork counterpart of PickerThumb). */
const ArtworkPickerThumb = ({ cand, busy, onApply }) => {
    const [failed, setFailed] = useState(false);
    return (
        <button
            type="button"
            disabled={busy}
            onClick={() => onApply(cand.poster_id)}
            title={cand.would_match ? 'Would match' : cand.reason}
            className={`group relative rounded-lg overflow-hidden border text-left ${
                cand.would_match ? 'border-success/60' : 'border-border'
            } hover:border-brand-primary disabled:opacity-50`}
        >
            <div
                className="flex items-center justify-center"
                style={{ aspectRatio: '3 / 2', ...ARTWORK_TRANSPARENCY_BG }}
            >
                {failed ? (
                    <span className="material-symbols-outlined text-fg-subtle text-3xl">
                        broken_image
                    </span>
                ) : (
                    <img
                        src={postersAPI.getThumbnailUrl(cand.poster_id, 200)}
                        alt={cand.title || `#${cand.poster_id}`}
                        loading="lazy"
                        className="object-contain w-full h-full p-2"
                        onError={() => setFailed(true)}
                    />
                )}
            </div>
            <div className="px-2 py-1">
                <p className="text-xs text-fg-muted truncate">{cand.style || cand.owner || '—'}</p>
                {cand.season_number != null && (
                    <p className="text-[10px] text-fg-subtle">Season {cand.season_number}</p>
                )}
            </div>
            <span className="absolute inset-0 flex items-center justify-center bg-primary/80 opacity-0 group-hover:opacity-100 transition-opacity">
                <span className="material-symbols-outlined text-white">check</span>
            </span>
        </button>
    );
};

const ARTWORK_TYPE_LABELS = { logo: 'Logo', background: 'Background', squareart: 'Square art' };

/** Modal that fetches candidate artwork files for one (media, image_type) and
 *  applies the chosen one. The artwork counterpart of PosterPickerModal. When a
 *  row lacks more than one type, an inline selector switches between them. */
const ArtworkPickerModal = ({ item, imageTypes, onClose, onApplied }) => {
    const toast = useToast();
    const kind = item.asset_type === 'collection' ? 'collection' : 'media';
    // The types this row can pick (its missing/failed/locked set); fall back to
    // all three so the modal is always usable.
    const types = imageTypes?.length ? imageTypes : ['logo', 'background', 'squareart'];
    const [imageType, setImageType] = useState(types[0]);
    // Tag the fetched list with the type it was loaded for, so switching type
    // shows the loading state (candidates === null) without a synchronous
    // setState in the effect (react-hooks/set-state-in-effect).
    const [result, setResult] = useState({ type: null, list: null });
    const [busy, setBusy] = useState(null);

    useEffect(() => {
        let alive = true;
        postersAPI
            .fetchArtworkCandidates(item.id, imageType, { kind })
            .then(r => alive && setResult({ type: imageType, list: r?.data?.candidates || [] }))
            .catch(() => alive && setResult({ type: imageType, list: [] }));
        return () => {
            alive = false;
        };
    }, [item.id, imageType, kind]);

    const candidates = result.type === imageType ? result.list : null;

    const apply = async posterId => {
        setBusy(posterId);
        try {
            const res = await postersAPI.applyArtwork(item.id, imageType, posterId, { kind });
            toast.success(
                res?.message ||
                    (res?.data?.applied
                        ? 'Artwork applied'
                        : 'Artwork saved — applies on the next asset_renamerr run')
            );
            onApplied?.();
            onClose();
        } catch {
            toast.error('Failed to apply artwork');
            setBusy(null);
        }
    };

    const typeLabel = ARTWORK_TYPE_LABELS[imageType]?.toLowerCase() || imageType;

    return (
        <Modal isOpen onClose={onClose} size="large">
            <Modal.Header>
                Choose artwork — {item.title}
                {item.year ? ` (${item.year})` : ''}
                {item.season_number != null ? ` · Season ${item.season_number}` : ''}
            </Modal.Header>
            <Modal.Body>
                {types.length > 1 && (
                    <div className="flex flex-wrap gap-1 mb-3">
                        {types.map(t => (
                            <button
                                key={t}
                                type="button"
                                onClick={() => setImageType(t)}
                                className={`px-3 py-1 text-sm rounded-lg border ${
                                    imageType === t
                                        ? 'border-brand-primary/50 bg-surface-alt text-fg'
                                        : 'border-border text-fg-muted hover:text-fg'
                                }`}
                            >
                                {ARTWORK_TYPE_LABELS[t] || t}
                            </button>
                        ))}
                    </div>
                )}
                <p className="text-xs text-fg-subtle mb-3">
                    Applying follows Asset Renamerr&apos;s <strong>Apply Method</strong>: with{' '}
                    <strong>Plex</strong> the {typeLabel} is uploaded straight to Plex; with{' '}
                    <strong>Kometa</strong> it&apos;s copied into your assets directory. The pick is
                    saved &amp; locked either way.
                </p>
                {candidates === null ? (
                    <p className="text-sm text-fg-muted">Searching for artwork…</p>
                ) : candidates.length === 0 ? (
                    <p className="text-sm text-fg-muted">
                        No candidate {typeLabel} files found in your cache for this title.
                    </p>
                ) : (
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                        {candidates.map(c => (
                            <ArtworkPickerThumb
                                key={c.poster_id}
                                cand={c}
                                busy={busy != null}
                                onApply={apply}
                            />
                        ))}
                    </div>
                )}
            </Modal.Body>
        </Modal>
    );
};

const ResetControl = ({ assetClass, onComplete }) => {
    const toast = useToast();
    const [open, setOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const isArt = assetClass === 'art';
    const label = isArt ? 'Reset artwork coverage' : 'Reset poster matches';

    const doReset = async () => {
        setBusy(true);
        try {
            const res = isArt
                ? await systemAPI.resetArtworkMatches()
                : await systemAPI.resetPosterMatches();
            const n = isArt ? (res?.data?.deleted ?? 0) : (res?.data?.reset ?? 0);
            toast.success(
                isArt
                    ? `Artwork coverage reset — ${n} row(s) cleared`
                    : `Poster matches reset — ${n} item(s) returned to unmatched`
            );
            setOpen(false);
            onComplete?.();
        } catch {
            toast.error('Reset failed');
        } finally {
            setBusy(false);
        }
    };

    return (
        <>
            <Button
                variant="secondary"
                size="small"
                icon="restart_alt"
                onClick={() => setOpen(true)}
                title={`Reset the ${isArt ? 'additional-artwork' : 'poster'} figures to all-missing`}
            >
                {isArt ? 'Reset artwork' : 'Reset posters'}
            </Button>
            <Modal isOpen={open} onClose={() => !busy && setOpen(false)} size="small">
                <Modal.Header>{label}?</Modal.Header>
                <Modal.Body>
                    <div className="flex flex-col gap-3 text-sm text-fg-muted">
                        {isArt ? (
                            <p>
                                Clears all additional-artwork coverage (logos / backgrounds / square
                                art) back to all-missing. The next <strong>Asset Renamerr</strong>{' '}
                                run repopulates it. Your &ldquo;not needed&rdquo; (ignored) marks
                                are kept.
                            </p>
                        ) : (
                            <p>
                                Returns every matched poster to unmatched (media &amp; collections)
                                so the next <strong>Poster Renamerr</strong> run re-matches from
                                scratch. Your <strong>Ignored</strong> and <strong>Locked</strong>{' '}
                                items are kept.
                            </p>
                        )}
                        <p className="text-fg-subtle text-xs">
                            This only resets CHUB&apos;s tracking — it does not delete posters or
                            artwork from disk or Plex.
                        </p>
                    </div>
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="ghost" disabled={busy} onClick={() => setOpen(false)}>
                        Cancel
                    </Button>
                    <Button variant="danger" disabled={busy} onClick={doReset}>
                        {busy ? 'Resetting…' : label}
                    </Button>
                </Modal.Footer>
            </Modal>
        </>
    );
};

const UnmatchedAssetsPage = () => {
    const { data, isLoading, refresh } = useApiData({
        apiFunction: postersAPI.fetchUnmatchedDetails,
        options: { showErrorToast: false },
    });

    const summary = useMemo(() => data?.data?.summary || {}, [data]);
    const items = useMemo(() => data?.data?.unmatched || {}, [data]);
    const reviewRows = useMemo(() => data?.data?.needs_review || [], [data]);
    const ignoredRows = useMemo(() => data?.data?.ignored || [], [data]);
    const lockedRows = useMemo(() => data?.data?.locked || [], [data]);
    const grandTotal = summary.grand_total || {};

    const [viewMode, setViewMode] = useState('unmatched');
    const [pickerItem, setPickerItem] = useState(null);
    // Artwork picker target: { item, types } — the row plus the artwork types it
    // can pick (missing / failed / locked for the active tab).
    const [artworkPicker, setArtworkPicker] = useState(null);
    // Primary segregation: posters (default) vs additional artwork.
    const [assetClass, setAssetClass] = useState('poster');

    // Artwork coverage is fetched eagerly (in parallel with the poster data) so
    // the "Additional artwork" count badge is populated on first page load,
    // not only after the user opens that view.
    const {
        data: artworkData,
        isLoading: artworkLoading,
        refresh: refreshArtwork,
    } = useApiData({
        apiFunction: postersAPI.fetchUnmatchedArtwork,
        options: { showErrorToast: false },
    });
    const artworkLoaded = !!artworkData;

    const artworkSummary = artworkData?.data?.summary || {};
    const artworkCounts = {
        unmatched: artworkSummary.missing || 0,
        review: artworkSummary.needs_review || 0,
        locked: artworkSummary.locked || 0,
        ignored: artworkSummary.ignored || 0,
    };

    const posterViewCounts = {
        unmatched: grandTotal.unmatched || 0,
        review: reviewRows.length,
        locked: lockedRows.length,
        ignored: ignoredRows.length,
    };
    const viewCounts = assetClass === 'art' ? artworkCounts : posterViewCounts;

    // Type filter shared between the clickable summary cards and the list tabs.
    const [posterTypeFilter, setPosterTypeFilter] = useState('all');

    // The carousel shows the 50 posters CHUB most recently matched/applied to
    // media (newest first by matched_at) — genuine match recency, not
    // poster_cache insertion order (which biased toward whichever owner was
    // processed last in the scan).
    const { data: recentPostersData, refresh: refreshRecent } = useApiData({
        apiFunction: useCallback(() => postersAPI.fetchRecentlyMatched(50), []),
        options: { showErrorToast: false },
    });
    const recentPosters = useMemo(() => recentPostersData?.data?.items || [], [recentPostersData]);

    if (isLoading) return <Spinner size="large" text="Loading unmatched assets..." center />;

    const hasData = SUMMARY_TYPES.some(t => summary[t.key]?.total > 0);

    return (
        <div className="flex flex-col gap-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                    <h1 className="font-display text-[26px] font-bold tracking-[-0.3px] text-fg m-0">
                        Unmatched Assets
                    </h1>
                    <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">
                        Library items missing a poster or background — match a source or request the
                        artwork.
                    </p>
                </div>
                {grandTotal.total > 0 && (
                    <span className="font-mono text-[12px] text-fg-subtle whitespace-nowrap">
                        <span className="text-warning">{grandTotal.unmatched || 0}</span> unmatched
                        · {(grandTotal.percent_complete || 0).toFixed(1)}% complete
                    </span>
                )}
            </div>

            {recentPosters.length > 0 && (
                <RecentPosterReel posters={recentPosters} onRefresh={refreshRecent} />
            )}

            {/* Primary segregation: Posters (default) vs Additional artwork.
                Posters is what most users care about; artwork is one click away. */}
            <div className="flex items-center gap-3 flex-wrap">
                <div className="inline-flex p-1 gap-1 bg-surface-alt border border-border rounded-xl">
                    {[
                        {
                            key: 'poster',
                            label: '🖼️ Posters',
                            count: posterViewCounts.unmatched,
                        },
                        {
                            key: 'art',
                            label: '🎨 Additional artwork',
                            count: artworkLoaded ? artworkCounts.unmatched : null,
                        },
                    ].map(c => (
                        <button
                            key={c.key}
                            type="button"
                            onClick={() => {
                                // Reset to the default status tab when switching
                                // class so a stale "review/locked" view doesn't
                                // carry over between posters and artwork.
                                setViewMode('unmatched');
                                setAssetClass(c.key);
                            }}
                            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-colors ${
                                assetClass === c.key
                                    ? 'bg-primary text-on-color shadow-sm'
                                    : 'text-fg-muted hover:text-fg'
                            }`}
                        >
                            {c.label}
                            {c.count != null && (
                                <span
                                    className={`text-xs px-1.5 py-0.5 rounded-full ${
                                        assetClass === c.key
                                            ? 'bg-white/25 text-on-color'
                                            : 'bg-surface text-fg-muted'
                                    }`}
                                >
                                    {c.count}
                                </span>
                            )}
                        </button>
                    ))}
                </div>
                <span className="text-xs text-fg-subtle">
                    {assetClass === 'art'
                        ? 'Asset renamer for logos, backgrounds and square art'
                        : 'The main artwork shown in Plex.'}
                </span>
                {/* Both resets are always available, independent of the active
                    tab — one zeroes poster coverage, the other artwork. */}
                <div className="ml-auto flex items-center gap-2">
                    <ResetControl
                        assetClass="poster"
                        onComplete={() => {
                            refresh();
                            refreshRecent();
                        }}
                    />
                    <ResetControl assetClass="art" onComplete={refreshArtwork} />
                </div>
            </div>

            {/* View switch: Unmatched / Needs Review / Ignored */}
            <div className="flex flex-wrap gap-1">
                {STATUS_VIEWS.map(v => (
                    <button
                        key={v.key}
                        onClick={() => setViewMode(v.key)}
                        className={`px-3 py-1 text-sm rounded-lg border flex items-center gap-2 ${
                            viewMode === v.key
                                ? 'border-brand-primary/50 bg-surface-alt text-fg'
                                : 'border-border text-fg-muted hover:text-fg'
                        }`}
                    >
                        {v.label}
                        <span className="text-xs text-fg-subtle">{viewCounts[v.key]}</span>
                    </button>
                ))}
            </div>

            {assetClass === 'art' && (
                <ArtworkView
                    data={artworkData}
                    status={viewMode}
                    isLoading={artworkLoading && !artworkLoaded}
                    onRefresh={refreshArtwork}
                    onPick={(item, types) => setArtworkPicker({ item, types })}
                />
            )}

            {assetClass === 'poster' && viewMode === 'review' && (
                <MatchReviewList
                    rows={reviewRows}
                    mode="review"
                    onRefresh={refresh}
                    onPick={setPickerItem}
                />
            )}
            {assetClass === 'poster' && viewMode === 'locked' && (
                <MatchReviewList rows={lockedRows} mode="locked" onRefresh={refresh} />
            )}
            {assetClass === 'poster' && viewMode === 'ignored' && (
                <MatchReviewList rows={ignoredRows} mode="ignored" onRefresh={refresh} />
            )}
            {assetClass === 'poster' &&
                viewMode === 'unmatched' &&
                (!hasData ? (
                    <p className="text-sm text-fg-muted">
                        No unmatched-asset data yet. Run &ldquo;Run Unmatched Assets&rdquo; to scan
                        your library.
                    </p>
                ) : (
                    <>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            {SUMMARY_TYPES.map(({ key, label, icon }) => {
                                const typeData = summary[key] || {};
                                // Each summary card maps to a list filter; seasons
                                // live under the series list, so both point at it.
                                const filterFor = {
                                    movies: 'movie',
                                    series: 'series',
                                    seasons: 'series',
                                    collections: 'collection',
                                }[key];
                                const isActive = posterTypeFilter === filterFor;
                                return (
                                    <button
                                        key={key}
                                        type="button"
                                        onClick={() =>
                                            setPosterTypeFilter(isActive ? 'all' : filterFor)
                                        }
                                        title={
                                            isActive
                                                ? 'Filtering the list by this — click to clear'
                                                : `Filter the list to ${label.toLowerCase()}`
                                        }
                                        className={`text-left p-4 rounded-lg border transition-colors ${
                                            isActive
                                                ? 'bg-surface border-primary ring-1 ring-primary/40'
                                                : 'bg-surface border-border hover:border-primary/50'
                                        }`}
                                    >
                                        <p className="text-sm text-fg-muted flex items-center gap-1.5">
                                            <span className="text-base leading-none">{icon}</span>
                                            {label}
                                        </p>
                                        <p className="text-2xl font-bold text-warning">
                                            {typeData.unmatched || 0}
                                        </p>
                                        <p className="text-xs text-fg-subtle mt-1">
                                            of {typeData.total || 0} total &mdash;{' '}
                                            {typeData.percent_complete?.toFixed(1) || 0}% complete
                                        </p>
                                        {typeData.total > 0 && (
                                            <div className="mt-2 h-2 bg-surface-alt rounded-full overflow-hidden">
                                                <div
                                                    className="h-full bg-success rounded-full"
                                                    style={{
                                                        width: `${typeData.percent_complete || 0}%`,
                                                    }}
                                                />
                                            </div>
                                        )}
                                    </button>
                                );
                            })}
                        </div>

                        <UnmatchedList
                            items={items}
                            onRefresh={refresh}
                            onPick={setPickerItem}
                            typeKey={posterTypeFilter}
                            onTypeChange={setPosterTypeFilter}
                        />
                    </>
                ))}

            {pickerItem && (
                <PosterPickerModal
                    item={pickerItem}
                    onClose={() => setPickerItem(null)}
                    onApplied={refresh}
                />
            )}

            {artworkPicker && (
                <ArtworkPickerModal
                    item={artworkPicker.item}
                    imageTypes={artworkPicker.types}
                    onClose={() => setArtworkPicker(null)}
                    onApplied={refreshArtwork}
                />
            )}
        </div>
    );
};

export default UnmatchedAssetsPage;
