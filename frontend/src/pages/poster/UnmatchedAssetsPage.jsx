import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useApiData } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { postersAPI } from '../../utils/api/posters.js';
import { copyText } from '../../utils/clipboard.js';
import { buildPosterRequestText, formatId } from '../../utils/posterRequest.js';
import { IconButton, Modal, PageHeader } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';

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

/** A single poster in the reel: thumbnail with fallback + source-folder caption. */
const ReelPosterCard = ({ poster }) => {
    const [failed, setFailed] = useState(false);
    const caption = poster.folder || poster.style || poster.title || `#${poster.id}`;
    return (
        <div className="shrink-0" style={{ width: 112 }}>
            <div
                className="rounded-lg overflow-hidden border border-border bg-input shadow-md flex items-center justify-center"
                style={{ aspectRatio: '2 / 3' }}
                title={poster.title || poster.file || ''}
            >
                {failed ? (
                    <span className="material-symbols-outlined text-tertiary text-3xl">
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
            </div>
            <p className="mt-1 text-xs text-tertiary text-center truncate">{caption}</p>
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
                <h3 className="text-lg font-semibold text-primary flex items-center gap-2">
                    <span className="material-symbols-outlined text-brand-primary">movie</span>
                    Recently matched
                </h3>
                <div className="flex items-center gap-2 flex-wrap">
                    <div className="flex flex-wrap gap-1">
                        {REEL_FILTERS.map(f => (
                            <button
                                key={f.key}
                                onClick={() => selectFilter(f.key)}
                                className={`px-3 py-1 text-sm rounded-lg border ${
                                    filterKey === f.key
                                        ? 'border-brand-primary/50 bg-surface-alt text-primary'
                                        : 'border-border text-secondary hover:text-primary'
                                }`}
                            >
                                {f.label}
                            </button>
                        ))}
                    </div>
                    <span
                        className="text-xs text-tertiary text-center"
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

/** Unified, filterable + searchable table of every unmatched item. */
const UnmatchedList = ({ items, onRefresh }) => {
    const toast = useToast();
    const [typeKey, setTypeKey] = useState('all');
    const [query, setQuery] = useState('');
    const [busyId, setBusyId] = useState(null);

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
            <p className="text-sm text-secondary">
                Nothing unmatched — every tracked item has a poster.
            </p>
        );
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="flex flex-wrap gap-1">
                    {presentTabs.map(t => (
                        <button
                            key={t.key}
                            onClick={() => setTypeKey(t.key)}
                            className={`px-3 py-1 text-sm rounded-lg border ${
                                typeKey === t.key
                                    ? 'border-brand-primary/50 bg-surface-alt text-primary'
                                    : 'border-border text-secondary hover:text-primary'
                            }`}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>
                <input
                    type="text"
                    value={query}
                    onChange={e => setQuery(e.target.value)}
                    placeholder="Search title…"
                    aria-label="Search unmatched titles"
                    className="px-3 py-2 bg-input border border-border rounded-md text-primary text-sm"
                    style={{ minWidth: '14rem' }}
                />
            </div>
            {filtered.length === 0 ? (
                <p className="text-sm text-tertiary">No matches.</p>
            ) : (
                <div className="overflow-x-auto rounded-lg border border-border">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="bg-surface-alt text-secondary text-left">
                                <th className="px-3 py-2 font-medium">Title</th>
                                <th className="px-3 py-2 font-medium">Type</th>
                                <th className="px-3 py-2 font-medium">Year</th>
                                <th className="px-3 py-2 font-medium">Missing</th>
                                <th className="px-3 py-2 font-medium">Instance</th>
                                <th className="px-3 py-2 font-medium">TMDB</th>
                                <th className="px-3 py-2 font-medium">IMDB</th>
                                <th className="px-3 py-2 font-medium">TVDB</th>
                                <th className="px-3 py-2 font-medium text-right">Request</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                            {filtered.map((item, idx) => (
                                <tr
                                    key={`${item._type}-${item.tmdb_id || item.tvdb_id || item.title || idx}`}
                                    className="bg-surface hover:bg-surface-alt"
                                >
                                    <td className="px-3 py-2 text-primary">
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
                                    </td>
                                    <td className="px-3 py-2 text-secondary">
                                        {TYPE_LABELS[item._type]}
                                    </td>
                                    <td className="px-3 py-2 text-secondary">{item.year || '—'}</td>
                                    <td className="px-3 py-2 text-secondary">
                                        {item._type === 'series' ? (
                                            <>
                                                {item.missing_main_poster && (
                                                    <span className="text-warning">Main</span>
                                                )}
                                                {item.missing_main_poster &&
                                                    item.missing_seasons?.length > 0 &&
                                                    ', '}
                                                {item.missing_seasons?.length > 0 &&
                                                    `S${item.missing_seasons.join(', S')}`}
                                                {!item.missing_main_poster &&
                                                    !(item.missing_seasons?.length > 0) &&
                                                    '—'}
                                            </>
                                        ) : (
                                            '—'
                                        )}
                                    </td>
                                    <td className="px-3 py-2 text-secondary">
                                        {item.instance_name || '—'}
                                    </td>
                                    <td className="px-3 py-2 text-tertiary font-mono text-xs">
                                        {formatId(item.tmdb_id) || '—'}
                                    </td>
                                    <td className="px-3 py-2 text-tertiary font-mono text-xs">
                                        {formatId(item.imdb_id) || '—'}
                                    </td>
                                    <td className="px-3 py-2 text-tertiary font-mono text-xs">
                                        {formatId(item.tvdb_id) || '—'}
                                    </td>
                                    <td className="px-3 py-2 text-right whitespace-nowrap">
                                        {item._type !== 'collection' && (
                                            <IconButton
                                                icon="content_copy"
                                                size="small"
                                                variant="ghost"
                                                aria-label="Copy poster request to clipboard"
                                                title="Copy poster request"
                                                onClick={() => handleCopy(item)}
                                            />
                                        )}
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

const STATUS_VIEWS = [
    { key: 'unmatched', label: 'Unmatched' },
    { key: 'review', label: 'Needs Review' },
    { key: 'locked', label: 'Locked' },
    { key: 'ignored', label: 'Ignored' },
];

/** Colour for a 0–1 confidence score. */
const confidenceTone = c => {
    if (c == null) return 'text-tertiary';
    if (c >= 0.9) return 'text-success';
    if (c >= 0.7) return 'text-warning';
    return 'text-error';
};

const kindOf = row => (row.asset_type === 'collection' ? 'collection' : 'media');

/**
 * Flat table for the Needs-Review and Ignored tabs. Shows the match
 * confidence + reason the backend now records, plus per-row actions:
 * review → Approve / Ignore, ignored → Restore.
 */
const MatchReviewList = ({ rows, mode, onRefresh, onPick }) => {
    const toast = useToast();
    const [query, setQuery] = useState('');
    const [busyId, setBusyId] = useState(null);

    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        return rows.filter(r => !q || (r.title || '').toLowerCase().includes(q));
    }, [rows, query]);

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
        return <p className="text-sm text-secondary">{emptyMsg}</p>;
    }

    return (
        <div className="flex flex-col gap-3">
            <input
                type="text"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search title…"
                aria-label="Search titles"
                className="px-3 py-2 bg-input border border-border rounded-md text-primary text-sm self-start"
                style={{ minWidth: '14rem' }}
            />
            {filtered.length === 0 ? (
                <p className="text-sm text-tertiary">No matches.</p>
            ) : (
                <div className="overflow-x-auto rounded-lg border border-border">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="bg-surface-alt text-secondary text-left">
                                <th className="px-3 py-2 font-medium">Title</th>
                                <th className="px-3 py-2 font-medium">Type</th>
                                <th className="px-3 py-2 font-medium">Year</th>
                                <th className="px-3 py-2 font-medium">Instance</th>
                                <th className="px-3 py-2 font-medium">Confidence</th>
                                <th className="px-3 py-2 font-medium">Why</th>
                                <th className="px-3 py-2 font-medium text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                            {filtered.map((item, idx) => (
                                <tr
                                    key={`${item.id ?? idx}`}
                                    className="bg-surface hover:bg-surface-alt align-top"
                                >
                                    <td className="px-3 py-2 text-primary">
                                        <Link
                                            to={`/poster/search/assets?q=${encodeURIComponent(item.title || '')}`}
                                            className="hover:text-accent hover:underline"
                                            title="Search synced posters for this title"
                                        >
                                            {item.title}
                                        </Link>
                                    </td>
                                    <td className="px-3 py-2 text-secondary">
                                        {TYPE_LABELS[item.type] ||
                                            TYPE_LABELS[item.asset_type] ||
                                            item.type ||
                                            '—'}
                                    </td>
                                    <td className="px-3 py-2 text-secondary">{item.year || '—'}</td>
                                    <td className="px-3 py-2 text-secondary">
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
                                            <span className="text-tertiary">—</span>
                                        )}
                                    </td>
                                    <td className="px-3 py-2 text-secondary max-w-md">
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
const ArtworkView = ({ data, status, isLoading, onRefresh }) => {
    const toast = useToast();
    const [activeType, setActiveType] = useState('logo');
    const [query, setQuery] = useState('');
    const [busyKey, setBusyKey] = useState(null);

    const types = useMemo(() => data?.data?.types || {}, [data]);
    const activeMeta = ARTWORK_TYPES.find(a => a.key === activeType);

    // The status tab decides which per-type list we show (missing / review /
    // ignored). Locked has no artwork analogue, so it falls back to missing.
    const listKey =
        status === 'ignored'
            ? 'ignored_items'
            : status === 'review'
              ? 'needs_review_items'
              : 'missing_items';
    const rows = useMemo(() => {
        const list = types[activeType]?.[listKey] || [];
        const q = query.trim().toLowerCase();
        return q ? list.filter(r => (r.title || '').toLowerCase().includes(q)) : list;
    }, [types, activeType, listKey, query]);

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

    const setIgnored = async (item, ignored) => {
        const key = `${item.id}:${activeType}`;
        setBusyKey(key);
        try {
            await postersAPI.ignoreArtwork(item.id, activeType, {
                kind: item.asset_type === 'collection' ? 'collection' : 'media',
                ignored,
            });
            toast.success(ignored ? 'Marked not needed' : 'Restored');
            onRefresh();
        } catch {
            toast.error('Action failed');
        } finally {
            setBusyKey(null);
        }
    };

    if (isLoading) return <Spinner size="large" text="Loading artwork coverage..." center />;

    return (
        <div className="flex flex-col gap-4">
            {/* Per-type coverage cards — same style as the poster summary cards */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {ARTWORK_TYPES.map(({ key, label, icon }) => {
                    const t = types[key] || {};
                    const isActive = activeType === key;
                    return (
                        <button
                            key={key}
                            type="button"
                            onClick={() => setActiveType(key)}
                            className={`text-left p-4 rounded-lg border transition-colors ${
                                isActive
                                    ? 'bg-surface border-primary ring-1 ring-primary/40'
                                    : 'bg-surface border-border hover:border-primary/50'
                            }`}
                        >
                            <p className="text-sm text-secondary flex items-center gap-1.5">
                                <span className="text-base leading-none">{icon}</span>
                                {label}
                            </p>
                            <p className="text-2xl font-bold text-warning">{t.missing ?? 0}</p>
                            <p className="text-xs text-tertiary mt-1">
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

            <div className="flex items-center justify-between gap-3 flex-wrap">
                <input
                    type="text"
                    value={query}
                    onChange={e => setQuery(e.target.value)}
                    placeholder="Search title…"
                    aria-label="Search titles"
                    className="px-3 py-2 bg-input border border-border rounded-md text-primary text-sm"
                    style={{ minWidth: '14rem' }}
                />
                <Link
                    to="/settings/modules#asset_renamerr"
                    className="text-sm text-accent hover:underline whitespace-nowrap"
                    title="Configure / run the module that applies this artwork"
                >
                    ⚙️ Asset Renamerr settings
                </Link>
            </div>

            {rows.length === 0 ? (
                <p className="text-sm text-secondary">
                    {status === 'ignored'
                        ? 'Nothing marked “not needed” for this artwork type.'
                        : status === 'review'
                          ? 'Nothing to review for this artwork type.'
                          : `No media missing ${ARTWORK_TYPES.find(a => a.key === activeType)?.label.toLowerCase()}.`}
                </p>
            ) : (
                <div className="overflow-x-auto rounded-lg border border-border">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="bg-surface-alt text-secondary text-left">
                                <th className="px-3 py-2 font-medium">Title</th>
                                <th className="px-3 py-2 font-medium">Type</th>
                                <th className="px-3 py-2 font-medium">Year</th>
                                <th className="px-3 py-2 font-medium">Instance</th>
                                <th className="px-3 py-2 font-medium">
                                    {status === 'ignored' ? 'Not needed' : 'Missing'}
                                </th>
                                {status === 'review' && (
                                    <th className="px-3 py-2 font-medium">Why</th>
                                )}
                                <th className="px-3 py-2 font-medium text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                            {rows.map((item, idx) => {
                                const key = `${item.id}:${activeType}`;
                                const isIgnored = status === 'ignored';
                                return (
                                    <tr
                                        key={`${item.id ?? idx}`}
                                        className="bg-surface hover:bg-surface-alt align-top"
                                    >
                                        <td className="px-3 py-2 text-primary">
                                            <Link
                                                to={`/poster/search/assets?q=${encodeURIComponent(item.title || '')}`}
                                                className="hover:text-accent hover:underline"
                                                title="Search synced assets for this title"
                                            >
                                                {item.title}
                                            </Link>
                                        </td>
                                        <td className="px-3 py-2 text-secondary">
                                            {TYPE_LABELS[item.asset_type] || item.asset_type || '—'}
                                        </td>
                                        <td className="px-3 py-2 text-secondary">
                                            {item.year || '—'}
                                        </td>
                                        <td className="px-3 py-2 text-secondary">
                                            {item.instance_name || '—'}
                                        </td>
                                        <td className="px-3 py-2">
                                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-surface-alt text-secondary text-xs whitespace-nowrap">
                                                <span className="leading-none">
                                                    {activeMeta?.icon}
                                                </span>
                                                {activeMeta?.label}
                                            </span>
                                        </td>
                                        {status === 'review' && (
                                            <td className="px-3 py-2 text-secondary max-w-md">
                                                {item.reason || (
                                                    <span className="text-tertiary">
                                                        Apply failed — no detail recorded
                                                    </span>
                                                )}
                                            </td>
                                        )}
                                        <td className="px-3 py-2 text-right whitespace-nowrap">
                                            <IconButton
                                                icon="content_copy"
                                                size="small"
                                                variant="ghost"
                                                aria-label="Copy request"
                                                title="Copy a request for this artwork"
                                                onClick={() => copyRequest(item)}
                                            />
                                            {isIgnored ? (
                                                <IconButton
                                                    icon="undo"
                                                    size="small"
                                                    variant="ghost"
                                                    disabled={busyKey === key}
                                                    aria-label="Restore"
                                                    title="Restore — track this artwork again"
                                                    onClick={() => setIgnored(item, false)}
                                                />
                                            ) : (
                                                <IconButton
                                                    icon="block"
                                                    size="small"
                                                    variant="ghost"
                                                    disabled={busyKey === key}
                                                    aria-label="Not needed"
                                                    title="Not needed — stop tracking this artwork for this item"
                                                    onClick={() => setIgnored(item, true)}
                                                />
                                            )}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
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
                    <span className="material-symbols-outlined text-tertiary text-3xl">
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
                <p className="text-xs text-secondary truncate">{cand.style || cand.owner || '—'}</p>
                {cand.season_number != null && (
                    <p className="text-[10px] text-tertiary">Season {cand.season_number}</p>
                )}
            </div>
            <span className="absolute inset-0 flex items-center justify-center bg-brand-primary/80 opacity-0 group-hover:opacity-100 transition-opacity">
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
                <p className="text-xs text-tertiary mb-3">
                    Applying follows Poster Renamerr&apos;s <strong>Apply Method</strong>: with{' '}
                    <strong>Plex</strong> the poster is uploaded straight to Plex (for instances
                    you&apos;ve opted in); with <strong>Kometa</strong> it&apos;s copied into your
                    assets directory for Kometa to apply. The match is saved &amp; locked either
                    way.
                </p>
                {candidates === null ? (
                    <p className="text-sm text-secondary">Searching for posters…</p>
                ) : candidates.length === 0 ? (
                    <p className="text-sm text-secondary">
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
    // Primary segregation: posters (default) vs additional artwork.
    const [assetClass, setAssetClass] = useState('poster');

    // Artwork coverage is fetched lazily — only when the user opens that view —
    // so the default poster experience carries zero extra cost.
    const {
        data: artworkData,
        isLoading: artworkLoading,
        refresh: refreshArtwork,
    } = useApiData({
        apiFunction: postersAPI.fetchUnmatchedArtwork,
        options: { showErrorToast: false, immediate: false },
    });
    const artworkLoaded = !!artworkData;
    useEffect(() => {
        if (assetClass === 'art' && !artworkLoaded) refreshArtwork();
    }, [assetClass, artworkLoaded, refreshArtwork]);

    const artworkSummary = artworkData?.data?.summary || {};
    const artworkCounts = {
        unmatched: artworkSummary.missing || 0,
        review: artworkSummary.needs_review || 0,
        locked: 0,
        ignored: artworkSummary.ignored || 0,
    };

    const posterViewCounts = {
        unmatched: grandTotal.unmatched || 0,
        review: reviewRows.length,
        locked: lockedRows.length,
        ignored: ignoredRows.length,
    };
    const viewCounts = assetClass === 'art' ? artworkCounts : posterViewCounts;

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
        <div className="flex flex-col gap-6">
            <PageHeader
                title="Unmatched Assets"
                description="Media in your library with no matched poster — copy a request to ask for one."
                icon="warning"
            />
            {grandTotal.total > 0 && (
                <p className="text-sm text-secondary">
                    <span className="font-medium text-primary">{grandTotal.unmatched || 0}</span>{' '}
                    unmatched of {grandTotal.total.toLocaleString()} —{' '}
                    {(grandTotal.percent_complete || 0).toFixed(1)}% complete
                </p>
            )}

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
                                    : 'text-secondary hover:text-primary'
                            }`}
                        >
                            {c.label}
                            {c.count != null && (
                                <span
                                    className={`text-xs px-1.5 py-0.5 rounded-full ${
                                        assetClass === c.key
                                            ? 'bg-white/25 text-on-color'
                                            : 'bg-surface text-secondary'
                                    }`}
                                >
                                    {c.count}
                                </span>
                            )}
                        </button>
                    ))}
                </div>
                <span className="text-xs text-tertiary">
                    {assetClass === 'art'
                        ? 'Optional extras (Asset Renamerr) — kept separate so posters stay primary.'
                        : 'The main artwork shown in Plex.'}
                </span>
            </div>

            {/* View switch: Unmatched / Needs Review / Ignored */}
            <div className="flex flex-wrap gap-1">
                {STATUS_VIEWS.map(v => (
                    <button
                        key={v.key}
                        onClick={() => setViewMode(v.key)}
                        className={`px-3 py-1 text-sm rounded-lg border flex items-center gap-2 ${
                            viewMode === v.key
                                ? 'border-brand-primary/50 bg-surface-alt text-primary'
                                : 'border-border text-secondary hover:text-primary'
                        }`}
                    >
                        {v.label}
                        <span className="text-xs text-tertiary">{viewCounts[v.key]}</span>
                    </button>
                ))}
            </div>

            {assetClass === 'art' && (
                <ArtworkView
                    data={artworkData}
                    status={viewMode}
                    isLoading={artworkLoading && !artworkLoaded}
                    onRefresh={refreshArtwork}
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
                    <p className="text-sm text-secondary">
                        No unmatched-asset data yet. Run &ldquo;Run Unmatched Assets&rdquo; to scan
                        your library.
                    </p>
                ) : (
                    <>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            {SUMMARY_TYPES.map(({ key, label, icon }) => {
                                const typeData = summary[key] || {};
                                return (
                                    <div
                                        key={key}
                                        className="p-4 rounded-lg bg-surface border border-border"
                                    >
                                        <p className="text-sm text-secondary flex items-center gap-1.5">
                                            <span className="text-base leading-none">{icon}</span>
                                            {label}
                                        </p>
                                        <p className="text-2xl font-bold text-warning">
                                            {typeData.unmatched || 0}
                                        </p>
                                        <p className="text-xs text-tertiary mt-1">
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
                                    </div>
                                );
                            })}
                        </div>

                        <UnmatchedList items={items} onRefresh={refresh} />
                    </>
                ))}

            {pickerItem && (
                <PosterPickerModal
                    item={pickerItem}
                    onClose={() => setPickerItem(null)}
                    onApplied={refresh}
                />
            )}
        </div>
    );
};

export default UnmatchedAssetsPage;
