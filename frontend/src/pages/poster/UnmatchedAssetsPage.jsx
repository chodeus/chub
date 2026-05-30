import React, { useCallback, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useApiData } from '../../hooks/useApiData.js';
import { useModuleExecution } from '../../hooks/useModuleExecution.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { postersAPI } from '../../utils/api/posters.js';
import { copyText } from '../../utils/clipboard.js';
import { buildPosterRequestText, formatId } from '../../utils/posterRequest.js';
import { IconButton, LoadingButton, PageHeader } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';

const SUMMARY_TYPES = [
    { key: 'movies', label: 'Movies' },
    { key: 'series', label: 'Series' },
    { key: 'seasons', label: 'Seasons' },
    { key: 'collections', label: 'Collections' },
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
                    Recently synced
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
const MatchReviewList = ({ rows, mode, onRefresh }) => {
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
        return (
            <p className="text-sm text-secondary">
                {mode === 'review'
                    ? 'Nothing to review — every match is confident.'
                    : 'No ignored items. Dismiss a row from Unmatched or Needs Review to park it here.'}
            </p>
        );
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

const UnmatchedAssetsPage = () => {
    const toast = useToast();
    const { executeModule, isRunning } = useModuleExecution();
    const { data, isLoading, refresh } = useApiData({
        apiFunction: postersAPI.fetchUnmatchedDetails,
        options: { showErrorToast: false },
    });

    const summary = useMemo(() => data?.data?.summary || {}, [data]);
    const items = useMemo(() => data?.data?.unmatched || {}, [data]);
    const reviewRows = useMemo(() => data?.data?.needs_review || [], [data]);
    const ignoredRows = useMemo(() => data?.data?.ignored || [], [data]);
    const grandTotal = summary.grand_total || {};

    const [viewMode, setViewMode] = useState('unmatched');

    const viewCounts = {
        unmatched: grandTotal.unmatched || 0,
        review: reviewRows.length,
        ignored: ignoredRows.length,
    };

    // The carousel shows the 50 most recently synced posters in sync order
    // (the backend orders poster_cache.created_at DESC). Epoch cutoff means
    // "all time" so it's the last 50 regardless of age, not a rolling window.
    const recentCutoff = useMemo(() => new Date(0).toISOString(), []);
    const { data: recentPostersData, refresh: refreshRecent } = useApiData({
        apiFunction: useCallback(
            () => postersAPI.fetchPostersAddedSince(recentCutoff, 50),
            [recentCutoff]
        ),
        options: { showErrorToast: false },
    });
    const recentPosters = useMemo(() => recentPostersData?.data?.items || [], [recentPostersData]);

    const handleRun = async () => {
        await executeModule('unmatched_assets');
    };
    const handleRefresh = () => {
        refresh();
        toast.success('Unmatched assets refreshed');
    };

    if (isLoading) return <Spinner size="large" text="Loading unmatched assets..." center />;

    const hasData = SUMMARY_TYPES.some(t => summary[t.key]?.total > 0);

    return (
        <div className="flex flex-col gap-6">
            <PageHeader
                title="Unmatched Assets"
                description="Media in your library with no matched poster — copy a request to ask for one."
                icon="warning"
            />
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                {grandTotal.total > 0 && (
                    <p className="text-sm text-secondary">
                        <span className="font-medium text-primary">
                            {grandTotal.unmatched || 0}
                        </span>{' '}
                        unmatched of {grandTotal.total.toLocaleString()} —{' '}
                        {(grandTotal.percent_complete || 0).toFixed(1)}% complete
                    </p>
                )}
                <div className="flex flex-wrap items-center gap-2 sm:gap-3 sm:ml-auto">
                    <IconButton
                        icon="refresh"
                        aria-label="Refresh unmatched assets"
                        variant="ghost"
                        onClick={handleRefresh}
                    />
                    <LoadingButton
                        loading={isRunning('unmatched_assets')}
                        loadingText="Running..."
                        variant="ghost"
                        icon="search_check"
                        onClick={handleRun}
                    >
                        Run Unmatched Assets
                    </LoadingButton>
                </div>
            </div>

            {recentPosters.length > 0 && (
                <RecentPosterReel posters={recentPosters} onRefresh={refreshRecent} />
            )}

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

            {viewMode === 'review' && (
                <MatchReviewList rows={reviewRows} mode="review" onRefresh={refresh} />
            )}
            {viewMode === 'ignored' && (
                <MatchReviewList rows={ignoredRows} mode="ignored" onRefresh={refresh} />
            )}
            {viewMode === 'unmatched' &&
                (!hasData ? (
                    <p className="text-sm text-secondary">
                        No unmatched-asset data yet. Run &ldquo;Run Unmatched Assets&rdquo; to scan
                        your library.
                    </p>
                ) : (
                    <>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            {SUMMARY_TYPES.map(({ key, label }) => {
                                const typeData = summary[key] || {};
                                return (
                                    <div
                                        key={key}
                                        className="p-4 rounded-lg bg-surface border border-border"
                                    >
                                        <p className="text-sm text-secondary">{label}</p>
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
        </div>
    );
};

export default UnmatchedAssetsPage;
