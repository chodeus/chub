import React, { useMemo, useState, useCallback } from 'react';
import { useApiData } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { postersAPI } from '../../utils/api/posters.js';
import { copyText } from '../../utils/clipboard.js';
import { buildPosterRequestText, formatId } from '../../utils/posterRequest.js';
import { IconButton, LoadingButton } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';

const PERIOD_OPTIONS = [
    { value: '', label: 'All Time' },
    { value: '7d', label: 'Last 7 Days' },
    { value: '30d', label: 'Last 30 Days' },
    { value: '90d', label: 'Last 90 Days' },
];

/** MB under 1 GB, GB under 1 TB, otherwise TB — keeps large sizes from showing noisy MB. */
const formatSize = bytes => {
    const mb = bytes / 1024 / 1024;
    if (mb >= 1024 * 1024) return `${(mb / 1024 / 1024).toFixed(1)} TB`;
    return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(0)} MB`;
};

/** Normalize a YYYYMMDD (or already-formatted) sync date to YYYY-MM-DD. */
const formatSyncDate = val =>
    val?.length === 8 ? `${val.slice(0, 4)}-${val.slice(4, 6)}-${val.slice(6, 8)}` : val;

/** Turn a {label: count} map into sorted bar data. `topN` collapses the tail
 * into an "Others" row; `labelMap` renames raw keys for display. */
const buildBars = (counts, { topN, labelMap } = {}) => {
    let entries = Object.entries(counts || {}).sort((a, b) => b[1] - a[1]);
    let othersCount = 0;
    if (topN && entries.length > topN) {
        othersCount = entries.slice(topN).reduce((sum, [, n]) => sum + n, 0);
        entries = entries.slice(0, topN);
    }
    const total = Object.values(counts || {}).reduce((sum, n) => sum + n, 0) || 1;
    const max = Math.max(...entries.map(([, n]) => n), othersCount, 1);
    const toBar = (label, count) => ({
        label,
        count,
        pct: (count / total) * 100,
        barPct: (count / max) * 100,
    });
    const bars = entries.map(([label, count]) => toBar(labelMap?.[label] || label, count));
    if (othersCount > 0) bars.push(toBar('Others', othersCount));
    return bars;
};

/** Horizontal bar list for a single breakdown chart. When `onSelect` is
 * provided each row becomes a button (used to drill into a variant). */
// Colour a "by source" bar by its source so Local/GDrive/CL2K/MM2K read
// distinctly (matching the mock). Other charts pass no barColor → cyan.
const sourceBarColor = label => {
    const l = (label || '').toLowerCase();
    if (l.includes('local')) return '#6cbc66';
    if (l.includes('drive') || l.includes('gdrive')) return '#53e8f0';
    if (l.includes('cl2k')) return '#a99eff';
    if (l.includes('mm2k')) return '#ffc944';
    return '#53e8f0';
};

// Avatar tints for the Top-contributors list (cycled by row index).
const CONTRIB_COLORS = ['#8767f7', '#53e8f0', '#6cbc66', '#ffc944', '#9a7ba9', '#fd355c'];

const BreakdownBars = ({ bars, onSelect, activeLabel, barColor }) => {
    const interactive = typeof onSelect === 'function';
    return (
        <div className="flex flex-col gap-3">
            {bars.map(({ label, count, pct, barPct }) => {
                const inner = (
                    <>
                        <div className="flex justify-between text-sm mb-1">
                            <span className={activeLabel === label ? 'text-accent' : 'text-fg'}>
                                {label}
                                {interactive && <span className="text-fg-subtle"> ›</span>}
                            </span>
                            <span className="font-mono text-xs text-fg-subtle">
                                {count.toLocaleString()} · {pct.toFixed(1)}%
                            </span>
                        </div>
                        <div className="h-2 bg-border rounded-full overflow-hidden">
                            <div
                                className="h-full rounded-full"
                                style={{
                                    width: `${barPct}%`,
                                    background: barColor ? barColor(label) : 'var(--accent)',
                                }}
                            />
                        </div>
                    </>
                );
                return interactive ? (
                    <button
                        key={label}
                        type="button"
                        onClick={() => onSelect(label)}
                        style={{
                            width: '100%',
                            textAlign: 'left',
                            cursor: 'pointer',
                            background: 'none',
                            border: 'none',
                            padding: 0,
                        }}
                    >
                        {inner}
                    </button>
                ) : (
                    <div key={label}>{inner}</div>
                );
            })}
        </div>
    );
};

const ASSET_TYPE_LABELS = {
    movie: 'Movies',
    show: 'Shows',
    season: 'Seasons',
    collection: 'Collections',
    other: 'Other',
};

const APPLIED_TYPE_FILTERS = [
    { key: 'all', label: 'All' },
    { key: 'movie', label: 'Movies' },
    { key: 'show', label: 'Shows' },
    { key: 'season', label: 'Seasons' },
];
const APPLIED_PAGE_SIZE = 50;

/** Drill-down table of media using a given poster variant, with a per-row
 * "copy request" button (same Discord block as Unmatched Assets). */
const AppliedVariantTable = ({ style }) => {
    const toast = useToast();
    const [typeKey, setTypeKey] = useState('all');
    const [offset, setOffset] = useState(0);
    const { data } = useApiData({
        apiFunction: useCallback(
            () =>
                postersAPI.fetchAppliedByStyle(style, {
                    type: typeKey === 'all' ? undefined : typeKey,
                    limit: APPLIED_PAGE_SIZE,
                    offset,
                }),
            [style, typeKey, offset]
        ),
        options: { showErrorToast: false },
        dependencies: [style, typeKey, offset],
    });
    const items = data?.data?.items || [];
    const total = data?.data?.total || 0;
    const page = Math.floor(offset / APPLIED_PAGE_SIZE) + 1;
    const pageCount = Math.max(1, Math.ceil(total / APPLIED_PAGE_SIZE));

    const selectType = key => {
        setTypeKey(key);
        setOffset(0);
    };

    const handleCopy = async item => {
        const built = buildPosterRequestText(
            item,
            item.resolved_type === 'movie' ? 'movie' : 'series'
        );
        if (!built) {
            toast.error('No TMDb/TVDb id available — cannot build a request link');
            return;
        }
        try {
            await copyText(built.text);
            toast.success('Poster request copied to clipboard');
        } catch {
            toast.error('Clipboard write failed');
        }
    };

    return (
        <div className="p-5 rounded-xl bg-surface border border-border">
            <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
                <p className="text-sm text-fg-muted">
                    <span className="text-fg font-medium">{style}</span> posters —{' '}
                    {total.toLocaleString()} items
                </p>
                <div className="flex flex-wrap gap-1">
                    {APPLIED_TYPE_FILTERS.map(f => (
                        <button
                            key={f.key}
                            onClick={() => selectType(f.key)}
                            className={`px-2 py-1 text-xs rounded-lg border ${
                                typeKey === f.key
                                    ? 'border-brand-primary/50 bg-surface-alt text-fg'
                                    : 'border-border text-fg-muted hover:text-fg'
                            }`}
                        >
                            {f.label}
                        </button>
                    ))}
                </div>
            </div>
            {items.length === 0 ? (
                <p className="text-sm text-fg-subtle">No matched media for this variant/type.</p>
            ) : (
                <>
                    <div
                        className="overflow-x-auto rounded-lg border border-border"
                        style={{ maxHeight: 340, overflowY: 'auto' }}
                    >
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="bg-surface-alt text-fg-muted text-left">
                                    <th className="px-3 py-2 font-medium">Title</th>
                                    <th className="px-3 py-2 font-medium">Type</th>
                                    <th className="px-3 py-2 font-medium">Year</th>
                                    <th className="px-3 py-2 font-medium">TMDB</th>
                                    <th className="px-3 py-2 font-medium text-right">Request</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border">
                                {items.map(item => (
                                    <tr key={item.id} className="bg-surface hover:bg-surface-alt">
                                        <td className="px-3 py-2 text-fg">{item.title}</td>
                                        <td className="px-3 py-2 text-fg-muted capitalize">
                                            {item.resolved_type}
                                            {item.resolved_type === 'season' &&
                                            item.season_number != null
                                                ? ` ${item.season_number}`
                                                : ''}
                                        </td>
                                        <td className="px-3 py-2 text-fg-muted">
                                            {item.year || '—'}
                                        </td>
                                        <td className="px-3 py-2 text-fg-subtle font-mono text-xs">
                                            {formatId(item.tmdb_id) || '—'}
                                        </td>
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
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    {pageCount > 1 && (
                        <div className="flex items-center justify-end gap-2 mt-3 text-sm text-fg-subtle">
                            <IconButton
                                icon="chevron_left"
                                size="small"
                                variant="ghost"
                                aria-label="Previous page"
                                disabled={page <= 1}
                                onClick={() => setOffset(o => Math.max(0, o - APPLIED_PAGE_SIZE))}
                            />
                            <span>
                                {page} / {pageCount}
                            </span>
                            <IconButton
                                icon="chevron_right"
                                size="small"
                                variant="ghost"
                                aria-label="Next page"
                                disabled={page >= pageCount}
                                onClick={() => setOffset(o => o + APPLIED_PAGE_SIZE)}
                            />
                        </div>
                    )}
                </>
            )}
        </div>
    );
};

const PosterStatsPage = () => {
    const toast = useToast();
    const [period, setPeriod] = useState('');
    const [variantsOpen, setVariantsOpen] = useState(false);

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

    // Low-resolution posters. 1000px is the existing backend default and
    // matches what most poster-source guidance considers the minimum for
    // a 16:9 / 2:3 display without obvious blurring.
    const [lowResThreshold, setLowResThreshold] = useState(1000);
    const { data: lowResData, refresh: refreshLowRes } = useApiData({
        apiFunction: useCallback(
            () => postersAPI.fetchLowResolutionPosters(lowResThreshold, 100),
            [lowResThreshold]
        ),
        options: { showErrorToast: false },
        dependencies: [lowResThreshold],
    });
    const lowResPosters = useMemo(() => lowResData?.data?.items || [], [lowResData]);
    const [isBackfilling, setIsBackfilling] = useState(false);
    const handleBackfillDimensions = useCallback(async () => {
        setIsBackfilling(true);
        try {
            await postersAPI.backfillPosterDimensions();
            toast.success('Dimension backfill triggered');
            refreshLowRes();
        } catch {
            toast.error('Backfill failed');
        } finally {
            setIsBackfilling(false);
        }
    }, [toast, refreshLowRes]);

    const stats = useMemo(() => statsData?.data || {}, [statsData]);
    // Always land on an ARRAY: the detail endpoints can return a bare object
    // ({} or {summary}) with no matched_stats/gdrive_stats key, and spreading
    // / reducing that downstream threw "x is not iterable" (the page crash).
    const matchedStats = useMemo(() => {
        const d = matchedDetailData?.data;
        // The detail endpoint keys this `matched_posters_stats`; /api/posters/stats
        // uses `matched_stats`. Read either (or a bare array) so the Top-contributors
        // list + matched table don't silently vanish on a key mismatch.
        const candidate =
            d?.matched_posters_stats ??
            d?.matched_stats ??
            (Array.isArray(d) ? d : null) ??
            stats.matched_posters_stats ??
            stats.matched_stats;
        return Array.isArray(candidate) ? candidate : [];
    }, [matchedDetailData, stats]);
    const gdriveStats = useMemo(() => {
        const candidate = gdriveDetailData?.data?.gdrive_stats ?? stats.gdrive_stats;
        return Array.isArray(candidate) ? candidate : [];
    }, [gdriveDetailData, stats]);
    const totalSyncedBytes = useMemo(
        () => gdriveStats.reduce((sum, s) => sum + (s.size_bytes || 0), 0),
        [gdriveStats]
    );
    // Library match completion summary — the full unmatched breakdown lives on
    // its own page (/poster/unmatched); here we only need the grand total.
    const grandTotal = useMemo(
        () => unmatchedDetailData?.data?.summary?.grand_total || {},
        [unmatchedDetailData]
    );
    // Breakdowns of posters actually applied to the library (not the full
    // GDrive catalog) — see backend get_applied_breakdowns.
    const variantBars = useMemo(() => buildBars(stats.applied_by_style), [stats]);
    const typeBars = useMemo(
        () => buildBars(stats.applied_by_type, { labelMap: ASSET_TYPE_LABELS }),
        [stats]
    );
    const sourceBars = useMemo(() => buildBars(stats.applied_by_source, { topN: 8 }), [stats]);

    // Top contributors: owners ranked by how many library items their posters
    // are matched to (owner aggregation already returned by /api/posters/stats).
    const contributors = useMemo(
        () =>
            [...matchedStats]
                .map(s => ({ name: s.owner || 'Unknown', count: s.media_matched || 0 }))
                .filter(c => c.count > 0)
                .sort((a, b) => b.count - a.count)
                .slice(0, 8),
        [matchedStats]
    );

    const handleRefresh = () => {
        refreshStats();
        refreshGDrive();
        refreshUnmatched();
        toast.success('Statistics refreshed');
    };

    if (isLoading) return <Spinner size="large" text="Loading statistics..." center />;

    return (
        <div className="flex flex-col gap-5">
            {/* Toolbar */}
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                    <h1 className="font-display text-[26px] font-bold tracking-[-0.3px] text-fg m-0">
                        Poster Statistics
                    </h1>
                    <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">
                        Asset-cache coverage, sources, and storage.
                    </p>
                </div>
                <div className="flex items-center gap-2.5">
                    <div className="flex items-center h-[38px] rounded-lg bg-surface border border-border">
                        <select
                            value={period}
                            onChange={e => setPeriod(e.target.value)}
                            className="h-full bg-transparent border-0 outline-none text-[13.5px] text-fg-muted px-3 cursor-pointer"
                            aria-label="Time period"
                        >
                            {PERIOD_OPTIONS.map(opt => (
                                <option key={opt.value} value={opt.value}>
                                    {opt.label}
                                </option>
                            ))}
                        </select>
                    </div>
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
                {[
                    {
                        label: 'CACHED ASSETS',
                        value: (stats.poster_cache_count || 0).toLocaleString(),
                        color: 'text-fg',
                        sub: 'posters + artwork',
                    },
                    {
                        label: 'MATCHED',
                        value: `${(grandTotal.percent_complete || 0).toFixed(1)}%`,
                        color: 'text-success',
                        sub:
                            grandTotal.total > 0
                                ? `${(grandTotal.total - grandTotal.unmatched).toLocaleString()} linked to library`
                                : null,
                    },
                    {
                        label: 'UNMATCHED',
                        value: (grandTotal.unmatched || 0).toLocaleString(),
                        color: 'text-warning',
                        sub: 'no library item',
                    },
                    {
                        label: 'SYNCED SIZE',
                        value: formatSize(totalSyncedBytes),
                        color: 'text-accent',
                        sub: `${gdriveStats.length} GDrive source${gdriveStats.length === 1 ? '' : 's'}`,
                    },
                ].map(card => (
                    <div
                        key={card.label}
                        className="p-5 rounded-xl bg-surface border border-border flex flex-col shadow-[0_2px_16px_-8px_rgba(0,0,0,0.6)]"
                    >
                        <p className="font-mono text-[10px] tracking-[1px] text-fg-subtle">
                            {card.label}
                        </p>
                        <p
                            className={`font-mono text-[28px] leading-none font-semibold mt-2 ${card.color}`}
                        >
                            {card.value}
                        </p>
                        <p
                            className="text-[11.5px] text-fg-subtle mt-1.5"
                            style={{ minHeight: '1rem' }}
                        >
                            {card.sub || ' '}
                        </p>
                    </div>
                ))}
            </div>

            {/* By source + By type (left), Top contributors (right) — mock layout */}
            {(sourceBars.length > 0 || typeBars.length > 0 || contributors.length > 0) && (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">
                    <div className="flex flex-col gap-5">
                        {sourceBars.length > 0 && (
                            <section>
                                <h2 className="font-display text-[15px] font-semibold text-fg mb-3">
                                    By source
                                </h2>
                                <div className="p-4 rounded-xl bg-surface border border-border">
                                    <BreakdownBars bars={sourceBars} barColor={sourceBarColor} />
                                </div>
                            </section>
                        )}
                        {typeBars.length > 0 && (
                            <section>
                                <h2 className="font-display text-[15px] font-semibold text-fg mb-3">
                                    By type
                                </h2>
                                <div className="p-4 rounded-xl bg-surface border border-border">
                                    <BreakdownBars bars={typeBars} />
                                </div>
                            </section>
                        )}
                    </div>
                    {contributors.length > 0 && (
                        <section>
                            <h2 className="font-display text-[15px] font-semibold text-fg mb-3">
                                Top contributors
                            </h2>
                            <div className="rounded-xl bg-surface border border-border overflow-hidden">
                                {contributors.map((c, i) => (
                                    <div
                                        key={`${c.name}-${i}`}
                                        className="flex items-center gap-3 px-4 py-3 border-b border-border-light last:border-0"
                                    >
                                        <span
                                            className="shrink-0 w-[30px] h-[30px] rounded-full flex items-center justify-center font-display text-[13px] font-bold"
                                            style={{
                                                background: `${CONTRIB_COLORS[i % CONTRIB_COLORS.length]}22`,
                                                color: CONTRIB_COLORS[i % CONTRIB_COLORS.length],
                                            }}
                                            aria-hidden="true"
                                        >
                                            {c.name.charAt(0).toUpperCase()}
                                        </span>
                                        <span className="flex-1 min-w-0 text-[13.5px] font-medium text-fg truncate">
                                            {c.name}
                                        </span>
                                        <span className="font-mono text-[12px] text-fg-subtle">
                                            {c.count.toLocaleString()}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </section>
                    )}
                </div>
            )}

            {/* Poster Breakdown — applied variant mix (interactive: click to request) */}
            {variantBars.length > 0 && (
                <section>
                    <h3 className="font-display text-lg font-semibold text-fg mb-1 flex items-center gap-2">
                        <span className="material-symbols-outlined text-brand-primary">
                            donut_small
                        </span>
                        Poster Breakdown
                    </h3>
                    <p className="text-xs text-fg-subtle mb-3">
                        Posters applied to your library — not the full GDrive catalog
                    </p>
                    <div className="p-5 rounded-xl bg-surface border border-border">
                        <p className="text-sm text-fg-muted mb-3">
                            By variant{' '}
                            <span className="text-fg-subtle">— click to list &amp; request</span>
                        </p>
                        <BreakdownBars
                            bars={variantBars}
                            onSelect={() => setVariantsOpen(o => !o)}
                        />
                    </div>
                    {variantsOpen && (
                        <div className="mt-4">
                            <div className="flex items-center justify-between gap-2 mb-2">
                                <p className="text-sm text-fg-muted">
                                    Pick titles to request the other variant
                                </p>
                                <IconButton
                                    icon="close"
                                    variant="ghost"
                                    aria-label="Hide variant lists"
                                    onClick={() => setVariantsOpen(false)}
                                />
                            </div>
                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                                {variantBars.map(b => (
                                    <AppliedVariantTable key={b.label} style={b.label} />
                                ))}
                            </div>
                        </div>
                    )}
                    {sourceBars.length > 0 && (
                        <div className="p-5 rounded-xl bg-surface border border-border mt-4">
                            <p className="text-sm text-fg-muted mb-3">Top sources used</p>
                            <BreakdownBars bars={sourceBars} barColor={sourceBarColor} />
                        </div>
                    )}
                </section>
            )}

            {/* Matched Poster Stats */}
            {Array.isArray(matchedStats) && matchedStats.length > 0 && (
                <section>
                    <h3 className="font-display text-lg font-semibold text-fg mb-3">
                        Matched Poster Stats
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {matchedStats.map((stat, i) => (
                            <div key={i} className="p-4 rounded-lg bg-surface border border-border">
                                <p className="font-medium text-fg mb-2">
                                    {stat.owner || `Source ${i + 1}`}
                                </p>
                                <div className="space-y-2 text-sm">
                                    <div>
                                        <div className="flex items-center justify-between text-fg-muted">
                                            <span>Media</span>
                                            <span>
                                                {stat.media_matched || 0}/{stat.media_total || 0}
                                            </span>
                                        </div>
                                        <div className="mt-1 h-2 bg-border rounded-full overflow-hidden">
                                            <div
                                                className="h-full bg-success rounded-full"
                                                style={{ width: `${stat.media_pct || 0}%` }}
                                            />
                                        </div>
                                    </div>
                                    <div>
                                        <div className="flex items-center justify-between text-fg-muted">
                                            <span>Collections</span>
                                            <span>
                                                {stat.collections_matched || 0}/
                                                {stat.collections_total || 0}
                                            </span>
                                        </div>
                                        <div className="mt-1 h-2 bg-border rounded-full overflow-hidden">
                                            <div
                                                className="h-full bg-accent rounded-full"
                                                style={{
                                                    width: `${stat.collections_pct || 0}%`,
                                                }}
                                            />
                                        </div>
                                    </div>
                                    <div className="flex items-center justify-between text-xs text-fg-subtle pt-1 border-t border-border">
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

            {/* Low-resolution Posters */}
            <section>
                <h3 className="font-display text-lg font-semibold text-fg mb-3 flex items-center gap-2">
                    <span className="material-symbols-outlined text-warning">
                        photo_size_select_small
                    </span>
                    Low-resolution posters
                </h3>
                <div className="flex flex-wrap items-center gap-3 mb-3">
                    <label className="flex items-center gap-2 text-sm text-fg-muted">
                        Below
                        <input
                            type="number"
                            min={100}
                            step={100}
                            value={lowResThreshold}
                            onChange={e =>
                                setLowResThreshold(Math.max(100, Number(e.target.value) || 100))
                            }
                            className="w-20 p-1.5 bg-input border border-border rounded-md text-fg text-sm"
                        />
                        px wide
                    </label>
                    <LoadingButton
                        variant="ghost"
                        icon="auto_fix_high"
                        loading={isBackfilling}
                        onClick={handleBackfillDimensions}
                    >
                        Backfill dimensions
                    </LoadingButton>
                </div>
                {lowResPosters.length === 0 ? (
                    <p className="text-sm text-fg-muted">
                        None found at this threshold. Run &ldquo;Backfill dimensions&rdquo; if you
                        haven&apos;t already — rows without recorded width are excluded.
                    </p>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                        {lowResPosters.slice(0, 30).map(p => (
                            <div
                                key={p.id}
                                className="flex items-center gap-2 p-2 rounded-lg bg-surface border border-border text-sm"
                                title={p.file || p.folder}
                            >
                                <span className="material-symbols-outlined text-warning text-base">
                                    warning
                                </span>
                                <span className="flex-1 min-w-0 truncate text-fg">
                                    {p.title || p.file || `#${p.id}`}
                                </span>
                                <span className="text-xs text-fg-subtle">
                                    {p.width ? `${p.width}px` : '—'}
                                </span>
                            </div>
                        ))}
                        {lowResPosters.length > 30 && (
                            <p className="col-span-full text-xs text-fg-subtle mt-1">
                                …and {lowResPosters.length - 30} more.
                            </p>
                        )}
                    </div>
                )}
            </section>

            {/* GDrive Sync Status */}
            {gdriveStats.length > 0 && (
                <section>
                    <h3 className="font-display text-lg font-semibold text-fg mb-3">
                        GDrive Sync Status
                    </h3>
                    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
                        {gdriveStats.map((stat, i) => (
                            <div
                                key={i}
                                className="flex items-center gap-2 p-2 rounded-lg bg-surface border border-border text-sm"
                                title={stat.folder_name || stat.owner || stat.location}
                            >
                                <span className="material-symbols-outlined text-brand-primary text-base">
                                    cloud_done
                                </span>
                                <span className="flex-1 min-w-0 truncate text-fg">
                                    {stat.folder_name || stat.owner || stat.location}
                                </span>
                                <span className="shrink-0 text-xs text-fg-subtle whitespace-nowrap">
                                    {stat.file_count || 0} files
                                    {stat.size_bytes > 0 && ` · ${formatSize(stat.size_bytes)}`}
                                    {stat.last_updated && ` · ${formatSyncDate(stat.last_updated)}`}
                                </span>
                            </div>
                        ))}
                    </div>
                </section>
            )}
        </div>
    );
};

export default PosterStatsPage;
