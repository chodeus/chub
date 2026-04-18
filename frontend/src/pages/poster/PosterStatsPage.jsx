import React, { useMemo, useState, useCallback } from 'react';
import { useApiData } from '../../hooks/useApiData.js';
import { useModuleExecution } from '../../hooks/useModuleExecution.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { postersAPI } from '../../utils/api/posters.js';
import { IconButton, LoadingButton, PageHeader } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';

const PERIOD_OPTIONS = [
    { value: '', label: 'All Time' },
    { value: '7d', label: 'Last 7 Days' },
    { value: '30d', label: 'Last 30 Days' },
    { value: '90d', label: 'Last 90 Days' },
];

/** Formats an external ID for display — returns null if empty/falsy */
const formatId = val => (val ? String(val) : null);

/** Collapsible table of unmatched items */
const UnmatchedTable = ({ title, items, type }) => {
    const [expanded, setExpanded] = useState(false);
    if (!items || items.length === 0) return null;

    return (
        <div className="mt-3">
            <button
                className="text-sm text-accent hover:underline flex items-center gap-1"
                onClick={() => setExpanded(!expanded)}
            >
                <span className="material-symbols-outlined text-base">
                    {expanded ? 'expand_less' : 'expand_more'}
                </span>
                {expanded ? 'Hide' : 'Show'} {items.length} unmatched {title.toLowerCase()}
            </button>
            {expanded && (
                <div className="mt-2 overflow-x-auto rounded-lg border border-border">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="bg-surface-alt text-secondary text-left">
                                <th className="px-3 py-2 font-medium">Title</th>
                                <th className="px-3 py-2 font-medium">Year</th>
                                {type === 'series' && (
                                    <th className="px-3 py-2 font-medium">Missing</th>
                                )}
                                <th className="px-3 py-2 font-medium">Instance</th>
                                <th className="px-3 py-2 font-medium">TMDB</th>
                                <th className="px-3 py-2 font-medium">IMDB</th>
                                <th className="px-3 py-2 font-medium">TVDB</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                            {items.map((item, idx) => (
                                <tr key={idx} className="bg-surface hover:bg-surface-alt">
                                    <td className="px-3 py-2 text-primary">{item.title}</td>
                                    <td className="px-3 py-2 text-secondary">{item.year || '—'}</td>
                                    {type === 'series' && (
                                        <td className="px-3 py-2 text-secondary">
                                            {item.missing_main_poster && (
                                                <span className="text-warning">Main poster</span>
                                            )}
                                            {item.missing_main_poster &&
                                                item.missing_seasons?.length > 0 &&
                                                ', '}
                                            {item.missing_seasons?.length > 0 &&
                                                `S${item.missing_seasons.join(', S')}`}
                                        </td>
                                    )}
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
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};

const PosterStatsPage = () => {
    const toast = useToast();
    const { executeModule, isRunning } = useModuleExecution();
    const [period, setPeriod] = useState('');

    const fetchStatsWithPeriod = useCallback(
        () => postersAPI.fetchStatistics(period ? { period } : {}),
        [period]
    );

    const {
        data: statsData,
        isLoading,
        refresh: refreshStats,
    } = useApiData({
        apiFunction: fetchStatsWithPeriod,
        options: { showErrorToast: false },
        dependencies: [period],
    });

    const { data: unmatchedDetailData, refresh: refreshUnmatched } = useApiData({
        apiFunction: postersAPI.fetchUnmatchedDetails,
        options: { showErrorToast: false },
    });

    const { data: matchedDetailData } = useApiData({
        apiFunction: postersAPI.fetchMatchedStats,
        options: { showErrorToast: false },
    });

    const { data: gdriveDetailData, refresh: refreshGDrive } = useApiData({
        apiFunction: postersAPI.fetchGDriveStats,
        options: { showErrorToast: false },
    });

    const stats = useMemo(() => statsData?.data || {}, [statsData]);
    const matchedStats = useMemo(
        () =>
            matchedDetailData?.data?.matched_stats ||
            matchedDetailData?.data ||
            stats.matched_stats ||
            [],
        [matchedDetailData, stats]
    );
    const gdriveStats = useMemo(
        () => gdriveDetailData?.data?.gdrive_stats || stats.gdrive_stats || [],
        [gdriveDetailData, stats]
    );
    const unmatchedSummary = useMemo(
        () => unmatchedDetailData?.data?.summary || {},
        [unmatchedDetailData]
    );
    const unmatchedItems = useMemo(
        () => unmatchedDetailData?.data?.unmatched || {},
        [unmatchedDetailData]
    );

    const handleRefresh = () => {
        refreshStats();
        refreshGDrive();
        refreshUnmatched();
        toast.success('Statistics refreshed');
    };

    const handleRunUnmatched = async () => {
        await executeModule('unmatched_assets');
    };

    if (isLoading) return <Spinner size="large" text="Loading statistics..." center />;

    const summaryTypes = [
        { key: 'movies', label: 'Movies' },
        { key: 'series', label: 'Series' },
        { key: 'seasons', label: 'Seasons' },
        { key: 'collections', label: 'Collections' },
    ];

    const hasUnmatched = summaryTypes.some(t => unmatchedSummary[t.key]?.unmatched > 0);

    return (
        <div className="flex flex-col gap-6">
            {/* Header */}
            <PageHeader
                title="Poster Statistics"
                description="View poster collection statistics and sync status."
                badge={4}
                icon="bar_chart"
            />
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-end gap-3">
                <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                    <select
                        value={period}
                        onChange={e => setPeriod(e.target.value)}
                        className="px-3 py-2 bg-surface border border-border rounded-md text-primary text-sm cursor-pointer"
                        aria-label="Time period"
                    >
                        {PERIOD_OPTIONS.map(opt => (
                            <option key={opt.value} value={opt.value}>
                                {opt.label}
                            </option>
                        ))}
                    </select>
                    <IconButton
                        icon="refresh"
                        aria-label="Refresh statistics"
                        variant="ghost"
                        onClick={handleRefresh}
                    />
                    <LoadingButton
                        loading={isRunning('unmatched_assets')}
                        loadingText="Running..."
                        variant="ghost"
                        icon="search_check"
                        onClick={handleRunUnmatched}
                    >
                        Run Unmatched Assets
                    </LoadingButton>
                </div>
            </div>

            {/* Summary Cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="p-5 rounded-xl bg-surface border border-border">
                    <p className="text-sm text-secondary mb-1">Cached Posters</p>
                    <p className="text-3xl font-bold text-primary">
                        {stats.poster_cache_count || 0}
                    </p>
                </div>
                <div className="p-5 rounded-xl bg-surface border border-border">
                    <p className="text-sm text-secondary mb-1">Orphaned Posters</p>
                    <p className="text-3xl font-bold text-warning">{stats.orphaned_count || 0}</p>
                </div>
                <div className="p-5 rounded-xl bg-surface border border-border">
                    <p className="text-sm text-secondary mb-1">GDrive Sources</p>
                    <p className="text-3xl font-bold text-primary">{gdriveStats.length}</p>
                </div>
            </div>

            {/* Unmatched Assets — Per-type Breakdown */}
            {hasUnmatched && (
                <section>
                    <h3 className="text-lg font-semibold text-primary mb-3 flex items-center gap-2">
                        <span className="material-symbols-outlined text-warning">warning</span>
                        Unmatched Assets
                    </h3>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        {summaryTypes.map(({ key, label }) => {
                            const data = unmatchedSummary[key] || {};
                            if (!data.total) return null;
                            return (
                                <div
                                    key={key}
                                    className="p-4 rounded-lg bg-surface border border-border"
                                >
                                    <p className="text-sm text-secondary">{label}</p>
                                    <p className="text-2xl font-bold text-warning">
                                        {data.unmatched || 0}
                                    </p>
                                    <p className="text-xs text-tertiary mt-1">
                                        of {data.total} total &mdash;{' '}
                                        {data.percent_complete?.toFixed(1) || 0}% complete
                                    </p>
                                    {data.total > 0 && (
                                        <div className="mt-2 h-1.5 bg-surface-alt rounded-full overflow-hidden">
                                            <div
                                                className="h-full bg-success rounded-full"
                                                style={{
                                                    width: `${data.percent_complete || 0}%`,
                                                }}
                                            />
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>

                    {/* Detail tables */}
                    <UnmatchedTable title="Movies" items={unmatchedItems.movies} type="movie" />
                    <UnmatchedTable title="Series" items={unmatchedItems.series} type="series" />
                    <UnmatchedTable
                        title="Collections"
                        items={unmatchedItems.collections}
                        type="collection"
                    />
                </section>
            )}

            {/* Matched Poster Stats */}
            {Array.isArray(matchedStats) && matchedStats.length > 0 && (
                <section>
                    <h3 className="text-lg font-semibold text-primary mb-3">
                        Matched Poster Stats
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {matchedStats.map((stat, i) => (
                            <div key={i} className="p-4 rounded-lg bg-surface border border-border">
                                <p className="font-medium text-primary mb-2">
                                    {stat.owner || `Source ${i + 1}`}
                                </p>
                                <div className="space-y-2 text-sm">
                                    <div>
                                        <div className="flex items-center justify-between text-secondary">
                                            <span>Media</span>
                                            <span>
                                                {stat.media_matched || 0}/{stat.media_total || 0}
                                            </span>
                                        </div>
                                        <div className="mt-1 h-1.5 bg-surface-alt rounded-full overflow-hidden">
                                            <div
                                                className="h-full bg-success rounded-full"
                                                style={{ width: `${stat.media_pct || 0}%` }}
                                            />
                                        </div>
                                    </div>
                                    <div>
                                        <div className="flex items-center justify-between text-secondary">
                                            <span>Collections</span>
                                            <span>
                                                {stat.collections_matched || 0}/
                                                {stat.collections_total || 0}
                                            </span>
                                        </div>
                                        <div className="mt-1 h-1.5 bg-surface-alt rounded-full overflow-hidden">
                                            <div
                                                className="h-full bg-brand-primary rounded-full"
                                                style={{
                                                    width: `${stat.collections_pct || 0}%`,
                                                }}
                                            />
                                        </div>
                                    </div>
                                    <div className="flex items-center justify-between text-xs text-tertiary pt-1 border-t border-border">
                                        <span>Overall</span>
                                        <span className="font-medium">
                                            {stat.overall_pct?.toFixed(1) || 0}% matched
                                        </span>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </section>
            )}

            {/* GDrive Sync Status */}
            {gdriveStats.length > 0 && (
                <section>
                    <h3 className="text-lg font-semibold text-primary mb-3">GDrive Sync Status</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {gdriveStats.map((stat, i) => (
                            <div key={i} className="p-4 rounded-lg bg-surface border border-border">
                                <div className="flex items-start gap-3">
                                    <span className="material-symbols-outlined text-brand-primary mt-0.5">
                                        cloud_done
                                    </span>
                                    <div className="flex-1 min-w-0">
                                        <p className="font-medium text-primary truncate">
                                            {stat.folder_name || stat.owner || stat.location}
                                        </p>
                                        <div className="flex items-center gap-3 text-sm text-secondary mt-1">
                                            <span>{stat.file_count || 0} files</span>
                                            {stat.size_bytes > 0 && (
                                                <span>
                                                    {(stat.size_bytes / 1024 / 1024).toFixed(1)} MB
                                                </span>
                                            )}
                                        </div>
                                        {stat.last_updated && (
                                            <p className="text-xs text-tertiary mt-1">
                                                Last synced:{' '}
                                                {stat.last_updated?.length === 8
                                                    ? `${stat.last_updated.slice(0, 4)}-${stat.last_updated.slice(4, 6)}-${stat.last_updated.slice(6, 8)}`
                                                    : stat.last_updated}
                                            </p>
                                        )}
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </section>
            )}
        </div>
    );
};

export default PosterStatsPage;
