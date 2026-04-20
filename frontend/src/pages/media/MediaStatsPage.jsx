import React, { useMemo, useState, useCallback } from 'react';
import { useApiData } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { mediaAPI } from '../../utils/api/media.js';
import { IconButton, PageHeader } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';

const PERIOD_OPTIONS = [
    { value: '', label: 'All Time' },
    { value: '7d', label: 'Last 7 Days' },
    { value: '30d', label: 'Last 30 Days' },
    { value: '90d', label: 'Last 90 Days' },
];

/** Reusable stat card — always reserves the subtext row so sibling cards align */
const StatCard = ({ label, value, subtext, color = 'text-primary' }) => (
    <div className="p-5 rounded-xl bg-surface border border-border flex flex-col">
        <p className="text-sm text-secondary mb-1">{label}</p>
        <p className={`text-3xl font-bold ${color}`}>{value}</p>
        <p className="text-xs text-tertiary mt-1 min-h-[1rem]">{subtext || '\u00a0'}</p>
    </div>
);

/** Reusable breakdown section */
const BreakdownSection = ({ title, items, labelKey, countKey = 'count', maxItems = null }) => {
    const [expanded, setExpanded] = useState(false);
    if (!items || items.length === 0) return null;

    const displayItems = maxItems && !expanded ? items.slice(0, maxItems) : items;
    const hasMore = maxItems && items.length > maxItems;

    return (
        <section>
            <h3 className="text-lg font-semibold text-primary mb-3">
                {title} ({items.length})
            </h3>
            <div className="flex flex-wrap gap-2">
                {displayItems.map((item, idx) => (
                    <span
                        key={item[labelKey] || idx}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-surface-alt text-sm"
                    >
                        <span className="text-primary capitalize">
                            {item[labelKey] || 'Unknown'}
                        </span>
                        <span className="text-tertiary font-medium">{item[countKey]}</span>
                    </span>
                ))}
            </div>
            {hasMore && (
                <button
                    className="mt-2 text-sm text-accent hover:underline"
                    onClick={() => setExpanded(!expanded)}
                >
                    {expanded ? 'Show less' : `Show all ${items.length}`}
                </button>
            )}
        </section>
    );
};

const MediaStatsPage = () => {
    const toast = useToast();
    const [period, setPeriod] = useState('');

    const fetchStats = useCallback(
        () => mediaAPI.fetchDetailedStatistics(period ? { period } : {}),
        [period]
    );

    const {
        data: statsData,
        isLoading,
        refresh: refreshStats,
    } = useApiData({
        apiFunction: fetchStats,
        options: { showErrorToast: false },
        dependencies: [period],
    });

    const stats = useMemo(() => statsData?.data || {}, [statsData]);
    const byType = useMemo(() => stats.by_type || [], [stats]);
    const monitored = useMemo(() => stats.monitored || {}, [stats]);

    const movieCount = useMemo(
        () => byType.find(r => r.asset_type === 'movie')?.total || 0,
        [byType]
    );
    const seriesCount = useMemo(
        () => byType.find(r => r.asset_type === 'show')?.total || 0,
        [byType]
    );

    const handleRefresh = () => {
        refreshStats();
        toast.success('Statistics refreshed');
    };

    if (isLoading) return <Spinner size="large" text="Loading statistics..." center />;

    return (
        <div className="flex flex-col gap-6">
            {/* Header */}
            <PageHeader
                title="Library Statistics"
                description="View media library statistics and analytics."
                badge={4}
                icon="bar_chart"
            />
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-end gap-3">
                <div className="flex flex-wrap items-center gap-2">
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
                </div>
            </div>

            {/* Summary Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <StatCard label="Total Media" value={stats.total || 0} />
                <StatCard label="Movies" value={movieCount} />
                <StatCard label="Series" value={seriesCount} />
                <StatCard
                    label="Monitored"
                    value={monitored.monitored || 0}
                    subtext={
                        monitored.unmonitored ? `${monitored.unmonitored} unmonitored` : undefined
                    }
                />
            </div>

            {/* By Type */}
            {byType.length > 0 && (
                <section>
                    <h3 className="text-lg font-semibold text-primary mb-3">By Type</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {byType.map(row => {
                            const zeroMatch = row.total > 0 && row.matched === 0;
                            return (
                                <div
                                    key={row.asset_type}
                                    className={`p-4 rounded-lg bg-surface border ${zeroMatch ? 'border-error/40' : 'border-border'}`}
                                    title={
                                        zeroMatch
                                            ? 'No matches found — check the configured sources for this type.'
                                            : undefined
                                    }
                                >
                                    <p className="text-sm font-medium text-primary capitalize mb-2 flex items-center gap-2">
                                        {row.asset_type}
                                        {zeroMatch && (
                                            <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-error/20 text-error">
                                                0% match
                                            </span>
                                        )}
                                    </p>
                                    <div className="flex items-baseline gap-3">
                                        <span className="text-2xl font-bold text-primary">
                                            {row.total}
                                        </span>
                                        <span
                                            className={`text-sm ${zeroMatch ? 'text-error' : 'text-success'}`}
                                        >
                                            {row.matched} matched
                                        </span>
                                        <span className="text-sm text-secondary">
                                            {row.instances} instance{row.instances !== 1 ? 's' : ''}
                                        </span>
                                    </div>
                                    {row.total > 0 && (
                                        <div className="mt-2 h-1.5 bg-surface-alt rounded-full overflow-hidden">
                                            <div
                                                className={`h-full rounded-full transition-all ${zeroMatch ? 'bg-error/70' : 'bg-success'}`}
                                                style={{
                                                    width: `${Math.max(4, Math.round((row.matched / row.total) * 100))}%`,
                                                }}
                                            />
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </section>
            )}

            {/* By Instance */}
            {stats.by_instance?.length > 0 && (
                <section>
                    <h3 className="text-lg font-semibold text-primary mb-3">By Instance</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {stats.by_instance.map(row => {
                            const zeroMatch = row.total > 0 && row.matched === 0;
                            return (
                                <div
                                    key={row.instance_name}
                                    className={`p-4 rounded-lg bg-surface border ${zeroMatch ? 'border-error/40' : 'border-border'}`}
                                    title={
                                        zeroMatch
                                            ? 'No matches found — the poster sources for this instance may be misconfigured.'
                                            : undefined
                                    }
                                >
                                    <p className="text-sm font-medium text-primary mb-2 flex items-center gap-2">
                                        {row.instance_name}
                                        {zeroMatch && (
                                            <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-error/20 text-error">
                                                0% match
                                            </span>
                                        )}
                                    </p>
                                    <div className="flex items-baseline gap-3">
                                        <span className="text-2xl font-bold text-primary">
                                            {row.total}
                                        </span>
                                        <span
                                            className={`text-sm ${zeroMatch ? 'text-error' : 'text-success'}`}
                                        >
                                            {row.matched} matched
                                        </span>
                                    </div>
                                    {row.total > 0 && (
                                        <div className="mt-2 h-1.5 bg-surface-alt rounded-full overflow-hidden">
                                            <div
                                                className={`h-full rounded-full transition-all ${zeroMatch ? 'bg-error/70' : 'bg-success'}`}
                                                style={{
                                                    width: `${Math.max(4, Math.round((row.matched / row.total) * 100))}%`,
                                                }}
                                            />
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </section>
            )}

            {/* By Status */}
            <BreakdownSection title="By Status" items={stats.by_status} labelKey="status" />

            {/* By Language */}
            <BreakdownSection title="By Language" items={stats.by_language} labelKey="language" />

            {/* By Rating */}
            <BreakdownSection title="By Rating" items={stats.by_rating} labelKey="rating" />

            {/* By Studio */}
            <BreakdownSection
                title="By Studio"
                items={stats.by_studio}
                labelKey="studio"
                maxItems={20}
            />

            {/* By Decade */}
            <BreakdownSection title="By Decade" items={stats.by_decade} labelKey="decade" />

            {/* By Genre */}
            <BreakdownSection title="By Genre" items={stats.by_genre} labelKey="genre" />

            {/* By Runtime */}
            <BreakdownSection title="By Runtime" items={stats.by_runtime} labelKey="bucket" />
        </div>
    );
};

export default MediaStatsPage;
