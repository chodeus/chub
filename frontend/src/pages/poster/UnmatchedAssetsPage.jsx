import React, { useMemo, useState } from 'react';
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

/** Collapsible table of unmatched items with a per-row "copy request" button. */
const UnmatchedTable = ({ title, items, type }) => {
    const [expanded, setExpanded] = useState(false);
    const toast = useToast();
    if (!items || items.length === 0) return null;

    const handleCopy = async item => {
        const built = buildPosterRequestText(item, type);
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
                                {type !== 'collection' && (
                                    <th className="px-3 py-2 font-medium text-right">Request</th>
                                )}
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                            {items.map((item, idx) => (
                                <tr key={idx} className="bg-surface hover:bg-surface-alt">
                                    <td className="px-3 py-2 text-primary">
                                        {type !== 'collection' ? (
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
                                    {type !== 'collection' && (
                                        <td className="px-3 py-2 text-right">
                                            <IconButton
                                                icon="content_copy"
                                                size="small"
                                                variant="ghost"
                                                aria-label="Copy poster request to clipboard"
                                                title="Copy poster request"
                                                onClick={() => handleCopy(item)}
                                            />
                                        </td>
                                    )}
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
    const grandTotal = summary.grand_total || {};

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

            {!hasData ? (
                <p className="text-sm text-secondary">
                    No unmatched-asset data yet. Run &ldquo;Run Unmatched Assets&rdquo; to scan your
                    library.
                </p>
            ) : (
                <section>
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

                    <UnmatchedTable title="Movies" items={items.movies} type="movie" />
                    <UnmatchedTable title="Series" items={items.series} type="series" />
                    <UnmatchedTable
                        title="Collections"
                        items={items.collections}
                        type="collection"
                    />
                </section>
            )}
        </div>
    );
};

export default UnmatchedAssetsPage;
