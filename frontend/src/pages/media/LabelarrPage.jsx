import React, { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useApiData, useApiMutation } from '../../hooks/useApiData.js';
import { labelarrAPI } from '../../utils/api/labelarr.js';
import { modulesAPI } from '../../utils/api/modules.js';
import { configAPI } from '../../utils/api/config.js';
import { LoadingButton, StatusDot } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';
import { formatDateTime } from '../../utils/datetime.js';
import { formatTimeAgo } from '../../utils/schedule.js';

// labels may be stored as a JSON-ish list or a comma string — normalise.
function toLabelList(labels) {
    if (Array.isArray(labels)) return labels.filter(Boolean);
    if (typeof labels === 'string' && labels.trim()) {
        return labels
            .split(',')
            .map(s => s.trim())
            .filter(Boolean);
    }
    return [];
}

const LabelarrPage = () => {
    const {
        data: statusData,
        isLoading,
        refresh: refreshStatus,
    } = useApiData({
        apiFunction: modulesAPI.fetchRunStates,
        options: { showErrorToast: false },
    });

    const { data: configData } = useApiData({
        apiFunction: configAPI.fetchConfig,
        options: { showErrorToast: false },
    });

    const { execute: runSync, isLoading: isSyncing } = useApiMutation(() => labelarrAPI.sync(), {
        successMessage: 'Label sync initiated',
        onSuccess: () => refreshStatus(),
    });

    const labelarrState = useMemo(() => statusData?.data?.labelarr || null, [statusData]);
    const labelarrCfg = useMemo(() => configData?.data?.labelarr || {}, [configData]);

    // Flatten config mappings to one row per (instance, label) pair so the
    // table reads as tag → label rows (matching the design). app_instance is
    // the *arr instance; labelarr mirrors each tag onto a Plex label of the
    // same name across the mapping's plex_instances.
    const rows = useMemo(() => {
        const out = [];
        for (const m of labelarrCfg.mappings || []) {
            const plex = (m.plex_instances || [])
                .map(p => p.instance || p.name || p.plex_instance || '')
                .filter(Boolean);
            for (const label of toLabelList(m.labels)) {
                out.push({ tag: label, instance: m.app_instance || '—', plex });
            }
        }
        return out;
    }, [labelarrCfg]);

    const status = labelarrState?.status || 'idle';
    const dotStatus =
        status === 'success'
            ? 'success'
            : status === 'error'
              ? 'error'
              : status === 'running'
                ? 'running'
                : 'idle';

    const stats = [
        { label: 'MAPPINGS', value: (labelarrCfg.mappings || []).length, tone: 'text-fg' },
        { label: 'LABELS', value: rows.length, tone: 'text-success' },
        {
            label: 'STATUS',
            value: status,
            tone:
                status === 'success'
                    ? 'text-success'
                    : status === 'error'
                      ? 'text-error'
                      : status === 'running'
                        ? 'text-accent'
                        : 'text-fg-muted',
            capitalize: true,
        },
        {
            label: 'LAST SYNC',
            value: labelarrState?.last_run
                ? formatTimeAgo(labelarrState.last_run, new Date())
                : 'Never',
            tone: 'text-fg-muted',
            title: labelarrState?.last_run ? formatDateTime(labelarrState.last_run) : undefined,
        },
    ];

    if (isLoading) return <Spinner size="large" text="Loading labelarr status..." center />;

    return (
        <div className="flex flex-col gap-5">
            {/* Toolbar */}
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                    <h1 className="font-display text-[26px] font-bold tracking-[-0.3px] text-fg m-0">
                        Label Sync
                    </h1>
                    <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">
                        Mirror Radarr / Sonarr tags onto Plex labels · managed by{' '}
                        <span className="font-mono text-fg-muted">labelarr</span>
                        {labelarrCfg.dry_run && (
                            <span className="ml-2 font-mono text-[10px] px-2 py-0.5 rounded-full bg-warning/15 text-warning align-middle">
                                DRY RUN
                            </span>
                        )}
                    </p>
                </div>
                <div className="flex items-center gap-2.5">
                    <LoadingButton
                        variant="surface"
                        icon="sync"
                        onClick={() => runSync()}
                        isLoading={isSyncing}
                    >
                        Sync now
                    </LoadingButton>
                    <Link
                        to="/settings/modules"
                        className="inline-flex items-center gap-1.5 h-[38px] px-4 rounded-lg bg-primary text-on-color font-display text-[13.5px] font-semibold no-underline hover:brightness-110 transition"
                        style={{ boxShadow: '0 4px 16px -5px var(--primary)' }}
                    >
                        <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
                            add
                        </span>
                        Add mapping
                    </Link>
                </div>
            </div>

            {/* Stats strip */}
            <div
                className="flex items-stretch flex-wrap bg-surface border border-border rounded-xl overflow-hidden"
                style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
            >
                {stats.map((s, i) => (
                    <React.Fragment key={s.label}>
                        {i > 0 && <div className="w-px self-stretch bg-border my-3" />}
                        <div className="px-[22px] py-3.5 flex flex-col gap-1.5 min-w-0 flex-1">
                            <span className="font-mono text-[10px] tracking-[1.2px] text-fg-subtle">
                                {s.label}
                            </span>
                            <span
                                className={`font-mono font-semibold text-[18px] ${s.tone} ${s.capitalize ? 'capitalize' : ''}`}
                                title={s.title}
                            >
                                {s.value}
                            </span>
                        </div>
                    </React.Fragment>
                ))}
            </div>

            {labelarrState?.message && (
                <div className="text-[12.5px] text-fg-muted bg-surface border border-border rounded-lg px-4 py-3">
                    {labelarrState.message}
                </div>
            )}

            {/* Mappings table (read-only — edit in Settings → Modules) */}
            <section
                className="bg-surface border border-border rounded-xl overflow-hidden"
                style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
            >
                <div className="flex items-center justify-between px-5 pt-4 pb-3.5">
                    <div>
                        <h2 className="font-display text-[15px] font-semibold text-fg m-0">
                            Mappings
                        </h2>
                        <p className="text-fg-subtle text-xs mt-0.5 mb-0">
                            Tag → Plex label across your instances
                        </p>
                    </div>
                    <Link
                        to="/settings/modules"
                        className="text-[12.5px] text-accent no-underline font-medium hover:underline"
                    >
                        Edit in Settings →
                    </Link>
                </div>
                {rows.length === 0 ? (
                    <div className="px-5 py-10 text-center text-sm text-fg-subtle border-t border-border">
                        No label mappings configured yet.
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <div className="min-w-[560px]">
                            <div className="grid grid-cols-[1.3fr_1.3fr_1.4fr_0.8fr] gap-3 px-5 py-2 border-y border-border font-mono text-[10px] tracking-[1px] text-fg-faint">
                                <span>ARR TAG</span>
                                <span>PLEX LABEL</span>
                                <span>INSTANCE</span>
                                <span>STATUS</span>
                            </div>
                            {rows.map((r, i) => (
                                <div
                                    key={`${r.instance}:${r.tag}:${i}`}
                                    className="grid grid-cols-[1.3fr_1.3fr_1.4fr_0.8fr] gap-3 items-center px-5 py-3 border-b border-border-light"
                                >
                                    <span className="font-mono text-xs text-source-cl2k truncate">
                                        {r.tag}
                                    </span>
                                    <span className="min-w-0">
                                        <span className="font-mono text-[11px] px-2 py-0.5 rounded-[5px] bg-warning/15 text-warning">
                                            {r.tag}
                                        </span>
                                    </span>
                                    <span
                                        className="font-mono text-[11.5px] text-fg-muted truncate"
                                        title={
                                            r.plex.length ? `Plex: ${r.plex.join(', ')}` : undefined
                                        }
                                    >
                                        {r.instance}
                                    </span>
                                    <span className="flex items-center gap-1.5 font-mono text-[11.5px] text-fg-data">
                                        <StatusDot status={dotStatus} size={6} ring={false} />
                                        <span className="capitalize">{status}</span>
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </section>
        </div>
    );
};

export default LabelarrPage;
