import React from 'react';
import { Button } from '../ui/button/Button';
import StatusDot from '../ui/StatusDot.jsx';
import Toggle from '../ui/Toggle.jsx';
import { humanize } from '../../utils/tools';

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

/**
 * Compact instance row — service avatar, name + type pill, URL · masked key,
 * health dot + ping/media, and Test / Sync / Edit / Delete / enable-toggle.
 */
export const InstanceCard = ({
    instance,
    serviceType,
    connectionStatus,
    healthStatus,
    instanceStats,
    isTesting,
    isSyncing,
    onTest,
    onSync,
    onEdit,
    onDelete,
    onToggle,
}) => {
    const [color, tint] = SERVICE_STYLE[serviceType] || ['#6582ca', 'rgba(101,130,202,.14)'];
    const name = humanize(instance.name);
    const initial = (instance.name || '?').charAt(0).toUpperCase();
    const enabled = instance.enabled !== false;

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

    const metaBits = [];
    if (ping != null) metaBits.push(`${ping} ms`);
    if (instanceStats?.total_media != null) {
        let m = `${instanceStats.total_media} total`;
        if (serviceType !== 'plex' && instanceStats.wanted_missing != null) {
            m += ` · ${instanceStats.wanted_missing} missing`;
        }
        metaBits.push(m);
    }

    const iconBtn =
        'w-8 h-8 rounded-lg flex items-center justify-center text-fg-muted hover:text-fg hover:bg-row-hover transition-colors disabled:opacity-50';

    return (
        <div className="flex items-center gap-4 px-[18px] py-[15px] rounded-xl bg-surface border border-border hover:border-[#3b3d72] transition-colors">
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
    );
};

export default InstanceCard;
