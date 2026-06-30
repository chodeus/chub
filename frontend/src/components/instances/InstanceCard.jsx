import React, { useState } from 'react';
import { Button } from '../ui/button/Button';
import StatusDot from '../ui/StatusDot.jsx';
import Toggle from '../ui/Toggle.jsx';
import { humanize } from '../../utils/tools';
import { formatDateTime } from '../../utils/datetime';
import { formatSecondsAgo } from '../../utils/schedule';

// Service identity colour + tint for the avatar / type pill.
const SERVICE_STYLE = {
    radarr: ['#6cbc66', 'rgba(108,188,102,.14)'],
    sonarr: ['#53e8f0', 'rgba(83,232,240,.14)'],
    lidarr: ['#9a7ba9', 'rgba(154,123,169,.16)'],
    plex: ['#ffc944', 'rgba(255,201,68,.14)'],
};

// Render an API key masked — dots plus the last few real chars (the config GET
// redacts secrets, so this is often all dots, which is fine).
const maskKey = key => {
    if (!key || typeof key !== 'string') return '';
    const tail = key.replace(/\*/g, '').slice(-4);
    return '•'.repeat(12) + tail;
};

// Relative "X ago" for the last-tested timestamp.
const formatTimestamp = timestamp => {
    if (!timestamp) return 'Never';
    const diff = Date.now() - timestamp;
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(minutes / 60);
    if (minutes < 1) return 'Just now';
    if (minutes < 60) return `${minutes} min${minutes > 1 ? 's' : ''} ago`;
    if (hours < 24) return `${hours} hour${hours > 1 ? 's' : ''} ago`;
    return formatDateTime(timestamp);
};

/**
 * Compact instance row — service avatar, name + type pill, URL · masked key,
 * health dot + ping, and Test / Sync / Edit / Delete / enable-toggle.
 * A chevron expands a detail panel with last-tested time, snapshot freshness,
 * and (for Plex) the per-library breakdown + libraries catalog with refresh.
 */
export const InstanceCard = ({
    instance,
    serviceType,
    connectionStatus,
    healthStatus,
    instanceStats,
    plexLibraries,
    isTesting,
    isSyncing,
    onTest,
    onSync,
    onEdit,
    onDelete,
    onToggle,
    onFetchLibraries,
}) => {
    const [expanded, setExpanded] = useState(false);
    const [color, tint] = SERVICE_STYLE[serviceType] || ['#6582ca', 'rgba(101,130,202,.14)'];
    const name = humanize(instance.name);
    const initial = (instance.name || '?').charAt(0).toUpperCase();
    const enabled = instance.enabled !== false;
    const isPlex = serviceType === 'plex';

    const hs = healthStatus?.status;
    const dotStatus = isTesting
        ? 'running'
        : hs === 'healthy'
          ? 'success'
          : hs === 'unhealthy'
            ? 'error'
            : connectionStatus
              ? connectionStatus.success
                  ? 'success'
                  : 'error'
              : 'idle';
    const healthLabel = isTesting
        ? 'Testing'
        : hs
          ? hs
          : connectionStatus
            ? connectionStatus.success
                ? 'Healthy'
                : 'Failed'
            : 'Not tested';
    const healthTone =
        dotStatus === 'success'
            ? 'text-success'
            : dotStatus === 'error'
              ? 'text-error'
              : dotStatus === 'running'
                ? 'text-accent'
                : 'text-fg-muted';
    const ping = healthStatus?.response_time_ms;

    // Connection/health meta only — library totals & missing counts live on the
    // Statistics page, not here.
    const metaBits = [];
    if (ping != null) metaBits.push(`${ping} ms`);

    const libraries = instanceStats?.libraries || {};
    const libEntries = Object.entries(libraries);
    const lastTested = connectionStatus?.timestamp
        ? formatTimestamp(connectionStatus.timestamp)
        : 'Never';
    const synced =
        instanceStats?.snapshot_age_seconds != null
            ? formatSecondsAgo(instanceStats.snapshot_age_seconds)
            : null;

    const iconBtn =
        'w-8 h-8 rounded-lg flex items-center justify-center text-fg-muted hover:text-fg hover:bg-row-hover transition-colors disabled:opacity-50';

    return (
        <div className="rounded-xl bg-surface border border-border hover:border-[#3b3d72] transition-colors overflow-hidden">
            <div className="flex items-center gap-4 px-[18px] py-[15px]">
                <span
                    className="shrink-0 w-11 h-11 rounded-[10px] flex items-center justify-center font-display text-[17px] font-bold"
                    style={{ background: tint, color }}
                    aria-hidden="true"
                >
                    {initial}
                </span>

                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 min-w-0">
                        <span className="font-display text-[15px] font-semibold text-fg truncate">
                            {name}
                        </span>
                        <span
                            className="shrink-0 font-mono text-[9px] uppercase tracking-[0.4px] px-1.5 py-0.5 rounded-[5px]"
                            style={{ color, background: tint }}
                        >
                            {serviceType}
                        </span>
                    </div>
                    <div
                        className="font-mono text-[11.5px] text-fg-data mt-1 truncate"
                        title={instance.url}
                    >
                        {instance.url || '—'}
                        {instance.api && (
                            <>
                                <span className="text-fg-dim"> · </span>
                                {maskKey(instance.api)}
                            </>
                        )}
                    </div>
                </div>

                <div className="hidden md:flex flex-col items-end gap-1 shrink-0 mr-1">
                    <span
                        className={`flex items-center gap-1.5 text-[12px] font-semibold ${healthTone}`}
                    >
                        <StatusDot status={dotStatus} size={7} ring={false} />
                        <span className="capitalize">{healthLabel}</span>
                    </span>
                    {metaBits.length > 0 && (
                        <span className="font-mono text-[10.5px] text-fg-subtle">
                            {metaBits.join(' · ')}
                        </span>
                    )}
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                    <Button variant="surface" size="small" onClick={onTest} disabled={isTesting}>
                        {isTesting ? 'Testing…' : 'Test'}
                    </Button>
                    <button
                        type="button"
                        onClick={onSync}
                        disabled={isSyncing}
                        className={iconBtn}
                        aria-label="Sync instance"
                        title="Sync"
                    >
                        <span className="material-symbols-outlined text-[18px]">sync</span>
                    </button>
                    <button
                        type="button"
                        onClick={onEdit}
                        className={iconBtn}
                        aria-label="Edit instance"
                        title="Edit"
                    >
                        <span className="material-symbols-outlined text-[18px]">edit</span>
                    </button>
                    <button
                        type="button"
                        onClick={onDelete}
                        className={`${iconBtn} hover:text-error`}
                        aria-label="Delete instance"
                        title="Delete"
                    >
                        <span className="material-symbols-outlined text-[18px]">delete</span>
                    </button>
                    <button
                        type="button"
                        onClick={() => setExpanded(e => !e)}
                        className={iconBtn}
                        aria-label={expanded ? 'Hide details' : 'Show details'}
                        aria-expanded={expanded}
                        title="Details"
                    >
                        <span
                            className="material-symbols-outlined text-[18px] transition-transform"
                            style={{ transform: expanded ? 'rotate(180deg)' : 'none' }}
                        >
                            expand_more
                        </span>
                    </button>
                    {onToggle && (
                        <Toggle
                            checked={enabled}
                            onChange={v => onToggle(instance.name, v)}
                            label={`Enable ${name}`}
                            className="ml-1"
                        />
                    )}
                </div>
            </div>

            {expanded && (
                <div className="px-[18px] pb-4 pt-1 border-t border-border-light flex flex-col gap-3 text-[12.5px]">
                    <div className="flex flex-wrap gap-x-6 gap-y-1 font-mono text-[11.5px] text-fg-subtle pt-3">
                        <span>
                            <span className="text-fg-dim">last tested</span>{' '}
                            <span className="text-fg-muted">{lastTested}</span>
                        </span>
                        {synced && (
                            <span>
                                <span className="text-fg-dim">synced</span>{' '}
                                <span className="text-fg-muted">{synced}</span>
                            </span>
                        )}
                    </div>

                    {/* Plex per-library breakdown */}
                    {isPlex && libEntries.length > 0 && (
                        <div className="font-mono text-[11.5px] text-fg-subtle flex flex-wrap gap-x-4 gap-y-1">
                            {libEntries.map(([lib, count]) => (
                                <span key={lib}>
                                    <span className="text-success">{count}</span> {lib}
                                </span>
                            ))}
                        </div>
                    )}

                    {/* Plex libraries catalog + refresh */}
                    {isPlex && (
                        <div>
                            <div className="flex items-center gap-2 mb-1.5">
                                <span className="font-mono text-[10px] uppercase tracking-[0.5px] text-fg-faint">
                                    Libraries
                                </span>
                                {onFetchLibraries && (
                                    <button
                                        type="button"
                                        onClick={() => onFetchLibraries(instance.name)}
                                        className="text-fg-subtle hover:text-fg text-xs"
                                        title="Refresh libraries"
                                        aria-label="Refresh libraries"
                                    >
                                        ↺
                                    </button>
                                )}
                            </div>
                            {plexLibraries && plexLibraries.length > 0 ? (
                                <div className="flex flex-wrap gap-1.5">
                                    {plexLibraries.map((lib, i) => {
                                        const title = typeof lib === 'string' ? lib : lib.title;
                                        const type = typeof lib === 'string' ? null : lib.type;
                                        return (
                                            <span
                                                key={i}
                                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-[5px] text-xs bg-surface-inset text-fg-muted"
                                            >
                                                <span>{title}</span>
                                                {type && (
                                                    <span className="text-fg-subtle">{type}</span>
                                                )}
                                            </span>
                                        );
                                    })}
                                </div>
                            ) : (
                                <button
                                    type="button"
                                    onClick={() =>
                                        onFetchLibraries && onFetchLibraries(instance.name)
                                    }
                                    className="text-xs text-fg-subtle hover:text-fg underline underline-offset-2"
                                >
                                    Load libraries
                                </button>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default InstanceCard;
