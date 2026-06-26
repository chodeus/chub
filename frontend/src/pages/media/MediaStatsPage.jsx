import React, { useMemo } from 'react';
import { useApiData } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { mediaAPI } from '../../utils/api/media.js';
import Spinner from '../../components/ui/Spinner.jsx';
import { formatSecondsAgo } from '../../utils/schedule';

/** Reusable stat card — always reserves the subtext row so sibling cards align */
const StatCard = ({ label, value, subtext, color = 'text-fg' }) => (
    <div className="p-5 rounded-xl bg-surface border border-border flex flex-col shadow-[0_2px_16px_-8px_rgba(0,0,0,0.6)]">
        <p className="font-mono text-[10px] tracking-[1.2px] uppercase text-fg-subtle mb-2">
            {label}
        </p>
        <p className={`font-mono text-[32px] leading-none font-bold ${color}`}>
            {(value || 0).toLocaleString()}
        </p>
        <p className="text-xs text-fg-subtle mt-2" style={{ minHeight: '1rem' }}>
            {subtext || ' '}
        </p>
    </div>
);

/** Completeness % for a health row: of monitored items, how many have their file.
 *  Falls back to in-library/total when nothing is monitored (e.g. all unmonitored). */
const completenessPct = row => {
    const monitored = row.monitored || 0;
    const missing = row.missing || 0;
    if (monitored > 0) return Math.round(((monitored - missing) / monitored) * 100);
    const total = row.total || 0;
    return total > 0 ? Math.round(((row.in_library || 0) / total) * 100) : 0;
};

/** Per-type / per-instance library-health card. */
const HealthCard = ({ title, badge, row, footer }) => {
    const missing = row.missing || 0;
    const inLibrary = row.in_library || 0;
    const pct = completenessPct(row);
    const hasMissing = missing > 0;
    return (
        <div
            className={`p-4 rounded-lg bg-surface border ${hasMissing ? 'border-warning/30' : 'border-border'} flex flex-col`}
            title={
                hasMissing
                    ? `${missing} monitored item${missing !== 1 ? 's' : ''} with no file yet`
                    : undefined
            }
        >
            <p className="text-sm font-medium text-fg mb-2 flex items-center gap-2 capitalize">
                <span className="truncate">{title}</span>
                {badge && (
                    <span
                        className="uppercase tracking-wider px-1.5 py-0.5 rounded bg-surface-alt text-fg-subtle shrink-0"
                        style={{ fontSize: '10px' }}
                    >
                        {badge}
                    </span>
                )}
            </p>
            <div className="flex items-baseline gap-3 flex-wrap">
                <span className="font-mono text-2xl font-bold text-fg">
                    {(row.total || 0).toLocaleString()}
                </span>
                <span className="font-mono text-sm text-success">
                    {inLibrary.toLocaleString()} in library
                </span>
                {hasMissing && (
                    <span className="font-mono text-sm text-warning">
                        {missing.toLocaleString()} missing
                    </span>
                )}
            </div>
            {(row.monitored > 0 || inLibrary > 0) && (
                <div className="mt-2 h-1.5 bg-border rounded-full overflow-hidden">
                    <div
                        className="h-full rounded-full transition-all bg-success"
                        style={{ width: `${Math.max(2, pct)}%` }}
                    />
                </div>
            )}
            <p className="text-xs text-fg-subtle mt-2" style={{ minHeight: '1rem' }}>
                {footer || `${pct}% complete`}
            </p>
        </div>
    );
};

const BreakdownBars = ({ items, labelKey, countKey = 'count', maxItems = null }) => {
    const [expanded, setExpanded] = React.useState(false);
    if (!items || items.length === 0) return null;

    const sortedItems = [...items].sort((a, b) => (b[countKey] ?? 0) - (a[countKey] ?? 0));
    const displayItems = maxItems && !expanded ? sortedItems.slice(0, maxItems) : sortedItems;
    const hasMore = maxItems && items.length > maxItems;
    const maxCount = sortedItems.reduce((m, it) => Math.max(m, it[countKey] ?? 0), 0) || 1;

    return (
        <div>
            <div className="flex flex-col gap-1.5">
                {displayItems.map((item, idx) => {
                    const count = item[countKey] ?? 0;
                    const pct = Math.round((count / maxCount) * 100);
                    return (
                        <div
                            key={item[labelKey] || idx}
                            className="grid items-center gap-3 text-sm"
                            style={{ gridTemplateColumns: 'minmax(6rem, 12rem) 1fr auto' }}
                        >
                            <span className="text-fg capitalize truncate">
                                {item[labelKey] || 'Unknown'}
                            </span>
                            <div
                                className="h-2 rounded-full bg-border overflow-hidden"
                                role="presentation"
                            >
                                <div
                                    className="h-full"
                                    style={{
                                        width: `${pct}%`,
                                        background: 'var(--accent)',
                                    }}
                                />
                            </div>
                            <span className="font-mono text-fg-data font-medium">
                                {count.toLocaleString()}
                            </span>
                        </div>
                    );
                })}
            </div>
            {hasMore && (
                <button
                    className="mt-3 text-sm text-accent hover:underline"
                    onClick={() => setExpanded(!expanded)}
                >
                    {expanded ? 'Show less' : `Show all ${items.length}`}
                </button>
            )}
        </div>
    );
};

const BREAKDOWN_TABS = [
    { key: 'by_status', label: 'Status', labelKey: 'status' },
    { key: 'by_root_folder', label: 'Root Folder', labelKey: 'root_folder', maxItems: 20 },
    { key: 'by_tags', label: 'Tags', labelKey: 'tag', maxItems: 20 },
    { key: 'by_genre', label: 'Genre', labelKey: 'genre' },
    { key: 'by_language', label: 'Language', labelKey: 'language' },
    { key: 'by_rating', label: 'Rating', labelKey: 'rating' },
    { key: 'by_studio', label: 'Studio', labelKey: 'studio', maxItems: 20 },
    { key: 'by_decade', label: 'Decade', labelKey: 'decade' },
    { key: 'by_runtime', label: 'Runtime', labelKey: 'bucket' },
];

const BreakdownTabs = ({ stats }) => {
    const availableTabs = BREAKDOWN_TABS.filter(tab => (stats[tab.key] || []).length > 0);
    const [activeKey, setActiveKey] = React.useState(null);

    const resolvedActive =
        activeKey && availableTabs.some(t => t.key === activeKey)
            ? activeKey
            : availableTabs[0]?.key;

    if (availableTabs.length === 0) return null;

    const activeTab = availableTabs.find(t => t.key === resolvedActive);
    const activeItems = stats[activeTab.key] || [];

    return (
        <section>
            <h3 className="text-lg font-semibold text-fg mb-3">Breakdowns</h3>
            <div className="flex flex-wrap gap-2 mb-4" role="tablist">
                {availableTabs.map(tab => {
                    const isActive = tab.key === resolvedActive;
                    const count = (stats[tab.key] || []).length;
                    return (
                        <button
                            key={tab.key}
                            role="tab"
                            aria-selected={isActive}
                            onClick={() => setActiveKey(tab.key)}
                            className="px-3 py-1.5 rounded-full text-sm transition-colors"
                            style={{
                                background: isActive
                                    ? 'color-mix(in srgb, var(--accent) 18%, transparent)'
                                    : 'var(--surface)',
                                border: `1px solid ${isActive ? 'var(--accent)' : 'var(--border)'}`,
                                color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                            }}
                        >
                            <span>{tab.label}</span>
                            <span
                                className="ml-2 text-fg-subtle font-medium tabular-nums"
                                style={{
                                    paddingLeft: '0.5rem',
                                    borderLeft: `1px solid ${
                                        isActive
                                            ? 'color-mix(in srgb, var(--accent) 40%, transparent)'
                                            : 'var(--border)'
                                    }`,
                                }}
                            >
                                {count}
                            </span>
                        </button>
                    );
                })}
            </div>
            <BreakdownBars
                key={activeTab.key}
                items={activeItems}
                labelKey={activeTab.labelKey}
                maxItems={activeTab.maxItems || null}
            />
        </section>
    );
};

/** Plex section — per-instance library item counts (Plex has no monitored/missing). */
const PlexSection = ({ plex }) => {
    const instances = plex?.instances || [];
    if (instances.length === 0) return null;
    return (
        <section>
            <h3 className="text-lg font-semibold text-fg mb-1">Plex Libraries</h3>
            <p className="text-sm text-fg-muted mb-3">
                Item counts per Plex library. Plex tracks presence only — no monitored or missing
                state.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {instances.map(inst => (
                    <div
                        key={inst.instance_name}
                        className="p-4 rounded-lg bg-surface border border-border flex flex-col"
                    >
                        <p className="text-sm font-medium text-fg mb-2 flex items-center gap-2">
                            <span className="truncate">{inst.instance_name}</span>
                            <span
                                className="uppercase tracking-wider px-1.5 py-0.5 rounded bg-surface-alt text-fg-subtle shrink-0"
                                style={{ fontSize: '10px' }}
                            >
                                plex
                            </span>
                        </p>
                        <span className="text-2xl font-bold text-fg mb-2">
                            {(inst.total || 0).toLocaleString()}
                        </span>
                        <BreakdownBars items={inst.libraries || []} labelKey="library_name" />
                        {inst.snapshot_age_seconds != null && (
                            <p className="text-xs text-fg-subtle mt-2">
                                Synced {formatSecondsAgo(inst.snapshot_age_seconds)}
                            </p>
                        )}
                    </div>
                ))}
            </div>
        </section>
    );
};

/** Recently Added — newest library items by first-seen time (created_at).
 *  Populates going forward only; pre-existing items have no first-seen stamp. */
const RecentlyAdded = ({ data }) => {
    const items = data?.items || [];
    const last7 = data?.last_7d || 0;
    const last30 = data?.last_30d || 0;
    return (
        <section>
            <h3 className="text-lg font-semibold text-fg mb-1">Recently Added</h3>
            <p className="text-sm text-fg-muted mb-3">
                {last7.toLocaleString()} in the last 7 days · {last30.toLocaleString()} in the last
                30 days
            </p>
            {items.length === 0 ? (
                <div className="p-4 rounded-lg bg-surface border border-border text-sm text-fg-subtle">
                    No additions tracked yet — newly added media will appear here as your instances
                    sync.
                </div>
            ) : (
                <div className="rounded-lg bg-surface border border-border overflow-hidden">
                    {items.map((item, idx) => (
                        <div
                            key={`${item.title}:${item.instance_name}:${idx}`}
                            className={`flex items-center gap-3 px-4 py-2.5 text-sm ${idx < items.length - 1 ? 'border-b border-border' : ''}`}
                        >
                            <span className="text-fg truncate flex-1 min-w-0">
                                {item.title}
                                {item.year ? (
                                    <span className="text-fg-subtle"> ({item.year})</span>
                                ) : null}
                            </span>
                            <span
                                className="uppercase tracking-wider px-1.5 py-0.5 rounded bg-surface-alt text-fg-subtle shrink-0"
                                style={{ fontSize: '10px' }}
                            >
                                {item.asset_type}
                            </span>
                            <span
                                className="text-fg-muted shrink-0 truncate hidden sm:inline"
                                style={{ maxWidth: '10rem' }}
                            >
                                {item.instance_name}
                            </span>
                            <span className="text-fg-subtle shrink-0 tabular-nums">
                                {formatSecondsAgo(item.added_age_seconds)}
                            </span>
                        </div>
                    ))}
                </div>
            )}
        </section>
    );
};

const MediaStatsPage = () => {
    const toast = useToast();

    const {
        data: statsData,
        isLoading,
        refresh: refreshStats,
    } = useApiData({
        apiFunction: mediaAPI.fetchDetailedStatistics,
        options: { showErrorToast: false },
    });

    const stats = useMemo(() => statsData?.data || {}, [statsData]);
    const byType = useMemo(() => stats.by_type || [], [stats]);
    const byInstance = useMemo(() => stats.by_instance || [], [stats]);
    const monitored = useMemo(() => stats.monitored || {}, [stats]);

    const monitoredCount = monitored.monitored || 0;
    const unmonitoredCount = monitored.unmonitored || 0;
    const inLibrary = stats.in_library || 0;
    const missing = stats.missing || 0;
    const completeness = completenessPct({
        monitored: monitoredCount,
        missing,
        total: stats.total,
        in_library: inLibrary,
    });

    const handleRefresh = () => {
        refreshStats();
        toast.success('Statistics refreshed');
    };

    if (isLoading) return <Spinner size="large" text="Loading statistics..." center />;

    return (
        <div className="flex flex-col gap-5">
            {/* Toolbar */}
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                    <h1 className="font-display text-[26px] font-bold tracking-[-0.3px] text-fg m-0">
                        Library Statistics
                    </h1>
                    <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">
                        Library health across Radarr, Sonarr, Lidarr and Plex.
                    </p>
                </div>
                <button
                    type="button"
                    onClick={handleRefresh}
                    className="inline-flex items-center gap-1.5 h-[38px] px-3.5 rounded-lg bg-surface border border-border text-fg-muted text-[13.5px] font-medium hover:bg-surface-elevated transition-colors"
                >
                    <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
                        refresh
                    </span>
                    Refresh
                </button>
            </div>

            {/* Summary Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <StatCard label="Total Media" value={stats.total || 0} />
                <StatCard
                    label="In Library"
                    value={inLibrary}
                    subtext={`${completeness}% of monitored present`}
                    color="text-success"
                />
                <StatCard
                    label="Monitored"
                    value={monitoredCount}
                    subtext={unmonitoredCount ? `${unmonitoredCount} unmonitored` : undefined}
                />
                <StatCard
                    label="Missing"
                    value={missing}
                    subtext="monitored, no file yet"
                    color={missing > 0 ? 'text-warning' : 'text-fg'}
                />
            </div>

            {/* Recently Added */}
            <RecentlyAdded data={stats.recently_added} />

            {/* By type + Breakdowns (side by side) */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">
                {byType.length > 0 ? (
                    <section>
                        <h3 className="font-display text-lg font-semibold text-fg mb-3">By type</h3>
                        <div className="grid grid-cols-1 gap-3">
                            {byType.map(row => (
                                <HealthCard
                                    key={row.asset_type}
                                    title={row.asset_type}
                                    badge={`${row.instances} instance${row.instances !== 1 ? 's' : ''}`}
                                    row={row}
                                />
                            ))}
                        </div>
                    </section>
                ) : (
                    <div />
                )}
                <BreakdownTabs stats={stats} />
            </div>

            {/* By Instance */}
            {byInstance.length > 0 && (
                <section>
                    <h3 className="text-lg font-semibold text-fg mb-3">By Instance</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {byInstance.map(row => (
                            <HealthCard
                                key={`${row.instance_name}:${row.source || ''}`}
                                title={row.instance_name}
                                badge={row.source}
                                row={row}
                                footer={
                                    row.snapshot_age_seconds != null
                                        ? `Synced ${formatSecondsAgo(row.snapshot_age_seconds)}`
                                        : undefined
                                }
                            />
                        ))}
                    </div>
                </section>
            )}

            {/* Plex */}
            <PlexSection plex={stats.plex} />
        </div>
    );
};

export default MediaStatsPage;
