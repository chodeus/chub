import React, { useMemo } from 'react';
import { useApiData } from '../../hooks/useApiData.js';
import { mediaAPI } from '../../utils/api/media.js';
import { instancesAPI } from '../../utils/api/instances.js';
import Spinner from '../../components/ui/Spinner.jsx';
import { ServiceIcon } from '../../components/ui/ServiceIcon.jsx';
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

/** Completeness %: of the acquirable units (have + still-missing), how many are
 *  present. Counted in content units (episodes/movies/albums); upcoming units
 *  aren't acquirable yet so they're excluded. */
const completenessPct = row => {
    const have = row.in_library || 0;
    const denom = have + (row.missing || 0);
    return denom > 0 ? Math.round((have / denom) * 100) : 100;
};

/** One labelled stat inside an instance row (e.g. Series / Seasons / Episodes).
 *  ``bar`` adds a completeness bar under the value for content metrics. */
const Metric = ({ label, value, sub, bar }) => (
    <div className="min-w-0">
        <p className="font-mono text-[10px] tracking-[1px] uppercase text-fg-subtle mb-1">
            {label}
        </p>
        <div className="flex items-baseline gap-2 flex-wrap">
            <span className="font-mono text-xl font-bold text-fg leading-none">
                {(value || 0).toLocaleString()}
            </span>
            {sub}
        </div>
        {bar != null && (
            <div
                className="mt-1.5 h-1.5 bg-border rounded-full overflow-hidden"
                style={{ minWidth: '130px' }}
            >
                <div
                    className="h-full rounded-full bg-success"
                    style={{ width: `${Math.max(2, bar)}%` }}
                />
            </div>
        )}
    </div>
);

/** Full-width instance row (mirrors the Instances page list): identity on the
 *  left, then the instance's stat breakdown — Sonarr shows series + seasons +
 *  episodes, Lidarr artists + albums, Radarr movies, Plex item count + the
 *  per-library breakdown. Content metrics carry the in-library/missing/upcoming
 *  health; container metrics (series/artists) carry their monitored count. */
const InstanceRow = ({ inst }) => {
    const isPlex = inst.source === 'plex';
    const pct = completenessPct(inst);
    const synced =
        inst.snapshot_age_seconds != null
            ? `Synced ${formatSecondsAgo(inst.snapshot_age_seconds)}`
            : null;

    const healthSub = (
        <span className="font-mono text-xs flex items-baseline gap-2 flex-wrap">
            <span className="text-success">
                {(inst.in_library || 0).toLocaleString()} in library
            </span>
            {(inst.missing || 0) > 0 && (
                <span className="text-warning">{inst.missing.toLocaleString()} missing</span>
            )}
            {(inst.upcoming || 0) > 0 && (
                <span className="text-fg-muted">{inst.upcoming.toLocaleString()} upcoming</span>
            )}
        </span>
    );
    const monitoredSub = n =>
        n ? (
            <span className="font-mono text-xs text-fg-muted">{n.toLocaleString()} monitored</span>
        ) : null;

    const metrics = [];
    if (inst.source === 'sonarr') {
        if (inst.show_count)
            metrics.push({
                key: 'series',
                label: 'Series',
                value: inst.show_count,
                sub: monitoredSub(inst.monitored_shows),
            });
        if (inst.season_count)
            metrics.push({ key: 'seasons', label: 'Seasons', value: inst.season_count });
        metrics.push({
            key: 'episodes',
            label: 'Episodes',
            value: inst.units,
            sub: healthSub,
            bar: pct,
        });
    } else if (inst.source === 'lidarr') {
        if (inst.artist_count)
            metrics.push({
                key: 'artists',
                label: 'Artists',
                value: inst.artist_count,
                sub: monitoredSub(inst.monitored_artists),
            });
        metrics.push({
            key: 'albums',
            label: 'Albums',
            value: inst.units,
            sub: healthSub,
            bar: pct,
        });
    } else if (!isPlex) {
        metrics.push({
            key: 'movies',
            label: 'Movies',
            value: inst.units,
            sub: healthSub,
            bar: pct,
        });
    }

    return (
        <div className="rounded-xl bg-surface border border-warning/30 px-[18px] py-[15px]">
            <div className="flex flex-wrap items-start gap-x-4 gap-y-1">
                <div className="w-full sm:w-[150px] shrink-0 min-w-0">
                    <span className="block font-display text-[15px] font-semibold text-fg truncate">
                        {inst.instance_name}
                    </span>
                </div>

                {isPlex ? (
                    <div className="flex-1 min-w-0 flex flex-col gap-2">
                        <Metric label="Items" value={inst.total || 0} />
                        <BreakdownBars items={inst.libraries || []} labelKey="library_name" />
                    </div>
                ) : (
                    <div className="flex-1 flex flex-wrap items-start gap-x-10 gap-y-3 min-w-0">
                        {metrics.map(m => (
                            <Metric
                                key={m.key}
                                label={m.label}
                                value={m.value}
                                sub={m.sub}
                                bar={m.bar}
                            />
                        ))}
                    </div>
                )}

                {synced && (
                    <span className="hidden sm:block text-xs text-fg-subtle shrink-0 whitespace-nowrap">
                        {synced}
                    </span>
                )}
            </div>
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
                    className="touch-expand mt-3 text-sm text-accent hover:underline"
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
                            className="inline-flex items-center min-h-11 px-3 rounded-full text-sm transition-colors"
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

/** Fallback service order if the /instances/types endpoint is unavailable —
 *  matches the Instances page default (Plex first). */
const FALLBACK_ORDER = ['plex', 'radarr', 'sonarr', 'lidarr'];
const TYPE_LABEL = { plex: 'Plex', radarr: 'Radarr', sonarr: 'Sonarr', lidarr: 'Lidarr' };

const MediaStatsPage = () => {
    const { data: statsData, isLoading } = useApiData({
        apiFunction: mediaAPI.fetchDetailedStatistics,
        options: { showErrorToast: false },
    });
    // Same source the Instances page orders by, so the two never drift.
    const { data: typesData } = useApiData({
        apiFunction: instancesAPI.fetchSupportedTypes,
        options: { showErrorToast: false },
    });

    const stats = useMemo(() => statsData?.data || {}, [statsData]);

    const orderRank = useMemo(() => {
        const types = typesData?.data?.types || typesData?.data;
        const names = Array.isArray(types)
            ? types.map(t => (typeof t === 'string' ? t : t.name || t.type))
            : FALLBACK_ORDER;
        const rank = {};
        names.forEach((n, i) => {
            if (n) rank[String(n).toLowerCase()] = i;
        });
        return rank;
    }, [typesData]);

    // One list: *arr instances (library-health) + Plex instances (item counts),
    // ordered like the Instances page, then by name within a service. Source is
    // lower-cased because media_cache historically stored it title-cased
    // ("Sonarr"), which must still match the lowercase order/label keys.
    const instances = useMemo(() => {
        const arr = (stats.by_instance || []).map(r => ({
            ...r,
            source: (r.source || '').toLowerCase(),
        }));
        const plex = (stats.plex?.instances || []).map(r => ({ ...r, source: 'plex' }));
        return [...arr, ...plex].sort((a, b) => {
            const ra = orderRank[a.source] ?? 99;
            const rb = orderRank[b.source] ?? 99;
            return ra !== rb
                ? ra - rb
                : (a.instance_name || '').localeCompare(b.instance_name || '');
        });
    }, [stats, orderRank]);

    // Group instances by service type, in Instances-page order; a type's
    // instances (e.g. radarr + radarr4k) become consecutive rows in its group.
    const instanceGroups = useMemo(() => {
        const groups = {};
        for (const inst of instances) {
            (groups[inst.source] ||= []).push(inst);
        }
        return Object.entries(groups).sort(
            (a, b) => (orderRank[a[0]] ?? 99) - (orderRank[b[0]] ?? 99)
        );
    }, [instances, orderRank]);

    const monitored = useMemo(() => stats.monitored || {}, [stats]);

    const monitoredCount = monitored.monitored || 0;
    const unmonitoredCount = monitored.unmonitored || 0;
    const inLibrary = stats.in_library || 0;
    const missing = stats.missing || 0;
    const upcoming = stats.upcoming || 0;
    const completeness = completenessPct({
        monitored: monitoredCount,
        missing,
        upcoming,
        total: stats.total,
        in_library: inLibrary,
    });

    if (isLoading) return <Spinner size="large" text="Loading statistics..." center />;

    return (
        <div className="flex flex-col gap-5">
            {/* Header — the page reflects the cache, which the instance syncs
                keep fresh; there's no manual refresh. */}
            <div className="min-w-0">
                <h1 className="font-display text-[26px] font-bold tracking-[-0.3px] text-fg m-0">
                    Library Statistics
                </h1>
                <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">
                    Library health across Radarr, Sonarr, Lidarr and Plex.
                </p>
            </div>

            {/* Summary Cards */}
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
                <StatCard label="Total Media" value={stats.total || 0} />
                <StatCard
                    label="In Library"
                    value={inLibrary}
                    subtext={`${completeness}% of released present`}
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
                    subtext="monitored, released, no file"
                    color={missing > 0 ? 'text-warning' : 'text-fg'}
                />
                <StatCard label="Upcoming" value={upcoming} subtext="monitored, not released yet" />
            </div>

            {/* By instance — grouped by service (Instances-page order), each a
                vertical list of full-width rows. */}
            {instanceGroups.map(([type, insts]) => (
                <section key={type}>
                    <h3 className="font-display text-[17px] font-semibold text-fg mb-3 flex items-center gap-2">
                        <ServiceIcon service={type} size="medium" />
                        {TYPE_LABEL[type] || type}
                    </h3>
                    <div className="flex flex-col gap-3">
                        {insts.map(inst => (
                            <InstanceRow key={`${inst.source}:${inst.instance_name}`} inst={inst} />
                        ))}
                    </div>
                </section>
            ))}

            {/* Breakdowns */}
            <BreakdownTabs stats={stats} />

            {/* Recently Added */}
            <RecentlyAdded data={stats.recently_added} />
        </div>
    );
};

export default MediaStatsPage;
