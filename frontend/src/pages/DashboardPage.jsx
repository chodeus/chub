import React, { useMemo, useEffect, useRef, useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { useApiData } from '../hooks/useApiData';
import { useModuleEvents } from '../hooks/useModuleEvents';
import { modulesAPI } from '../utils/api/modules';
import { jobsAPI } from '../utils/api/jobs';
import { systemAPI } from '../utils/api/system';
import { scheduleAPI } from '../utils/api/schedule';
import { instancesAPI } from '../utils/api/instances';
import { postersAPI } from '../utils/api/posters';
import { configAPI } from '../utils/api/config';
import { Button } from '../components/ui';
import { Modal } from '../components/modals/Modal';
import { Skeleton } from '../components/ui';
import Dropdown from '../components/ui/Dropdown.jsx';
import { useToast } from '../contexts/ToastContext.jsx';
import { humanize } from '../utils/tools.js';
import { formatDateTime } from '../utils/datetime.js';
import {
    scheduleToNextFire,
    scheduleToHuman,
    formatTimeUntil,
    formatTimeAgo,
} from '../utils/schedule.js';

const UPCOMING_LIMIT = 5;

// Status-dot colour + soft ring glow per run state. rgba glows aren't
// expressible as theme tokens, so the presentational hexes are inlined here
// (they mirror the redesign palette).
const DOT = {
    success: ['#6cbc66', 'rgba(108,188,102,.16)'],
    running: ['#53e8f0', 'rgba(83,232,240,.18)'],
    error: ['#fd355c', 'rgba(253,53,92,.18)'],
    pending: ['#ffc944', 'rgba(255,201,68,.16)'],
    idle: ['#564f8a', 'rgba(86,79,138,0)'],
};

// 7px status dot with a soft ring (box-shadow). status keys match DOT.
const StatusDot = ({ status = 'idle', size = 7 }) => {
    const [color, glow] = DOT[status] || DOT.idle;
    return (
        <span
            className="shrink-0 rounded-full"
            style={{ width: size, height: size, background: color, boxShadow: `0 0 0 3px ${glow}` }}
            aria-hidden="true"
        />
    );
};

const DashboardPage = () => {
    const toast = useToast();
    const [tick, setTick] = useState(() => Date.now());
    // Module name awaiting confirmation before Run-now fires. Prevents
    // misclicks on tiny inline "Run now" links from launching a module.
    const [runNowTarget, setRunNowTarget] = useState(null);
    // Collapsible modules-table rows: module name -> open. Default collapsed.
    const [expandedRows, setExpandedRows] = useState({});
    const toggleRow = useCallback(name => setExpandedRows(s => ({ ...s, [name]: !s[name] })), []);
    // "New run" toolbar dropdown (module picker → run-now confirm modal).
    const [newRunOpen, setNewRunOpen] = useState(false);
    const newRunRef = useRef(null);

    const {
        data: runStatesData,
        isLoading: runStatesLoading,
        refresh: refreshRunStates,
    } = useApiData({
        apiFunction: modulesAPI.fetchRunStates,
        options: { showErrorToast: false },
    });

    const {
        data: jobStatsData,
        isLoading: jobsLoading,
        refresh: refreshJobStats,
    } = useApiData({
        apiFunction: jobsAPI.getStats,
        options: { showErrorToast: false },
    });

    const {
        data: modulesData,
        isLoading: modulesLoading,
        refresh: refreshModules,
    } = useApiData({
        apiFunction: modulesAPI.fetchModules,
        options: { showErrorToast: false },
    });

    const {
        data: scheduleData,
        isLoading: scheduleLoading,
        refresh: refreshSchedules,
    } = useApiData({
        apiFunction: scheduleAPI.fetchSchedules,
        options: { showErrorToast: false },
    });

    const { data: diskData } = useApiData({
        apiFunction: systemAPI.getDiskUsage,
        options: { showErrorToast: false },
    });

    const { data: instancesRaw } = useApiData({
        apiFunction: instancesAPI.fetchInstances,
        options: { showErrorToast: false },
    });

    // Drives the user-customizable dashboard knobs (general.dashboard_*).
    const { data: configData } = useApiData({
        apiFunction: configAPI.fetchConfig,
        options: { showErrorToast: false },
    });

    // General config drives the dashboard knobs. Derived here (before the
    // refresh effects below) so the interval value is in scope for them.
    const dashboardCfg = useMemo(() => configData?.data?.general || {}, [configData]);
    const refreshSeconds = dashboardCfg.dashboard_refresh_seconds ?? 30;
    const upcomingLimit = dashboardCfg.dashboard_upcoming_limit ?? UPCOMING_LIMIT;

    // Countdown / poll-fallback tick. refreshSeconds = 0 turns auto-refresh off.
    useEffect(() => {
        if (refreshSeconds <= 0) return undefined;
        const id = setInterval(() => setTick(Date.now()), refreshSeconds * 1000);
        return () => clearInterval(id);
    }, [refreshSeconds]);

    // Most-recent errored job — drives the "Last failure" health card. A
    // single-row fetch so it stays cheap; surfaces a usable signal instead of
    // the all-time "failed count" which grows monotonically and tells you
    // nothing about current health.
    const { data: lastFailureData } = useApiData({
        apiFunction: useCallback(() => jobsAPI.listJobs({ status: 'error', limit: 1 }), []),
        options: { showErrorToast: false },
    });

    // Poster stats feed the orphan-count + cached-posters health cards.
    const { data: posterStatsData } = useApiData({
        apiFunction: postersAPI.fetchStatistics,
        options: { showErrorToast: false },
    });

    // Scheduler-written health snapshots — used to compute uptime % per
    // instance over the last 7 days and the most-recent reachability state.
    const { data: healthSnapshotsData } = useApiData({
        apiFunction: useCallback(() => systemAPI.getHealthSnapshots({ limit: 500 }), []),
        options: { showErrorToast: false },
    });

    const handleStatusChange = useCallback(() => {
        refreshRunStates();
        refreshJobStats();
        // Also refresh the modules list: the "Up next" running indicator + the
        // RUNNING count read each module's `running` flag, which only updates
        // from fetchModules — without this it lingers as "running" after a run
        // ends (SSE only refreshed run-states/jobs).
        refreshModules();
    }, [refreshRunStates, refreshJobStats, refreshModules]);

    const { isConnected } = useModuleEvents({ onStatusChange: handleStatusChange });

    const pollRef = useRef(null);
    useEffect(() => {
        // SSE-connected, or auto-refresh disabled → no polling fallback.
        if (isConnected || refreshSeconds <= 0) {
            if (pollRef.current) clearInterval(pollRef.current);
            return undefined;
        }
        pollRef.current = setInterval(() => {
            refreshRunStates();
            refreshJobStats();
            refreshModules();
        }, refreshSeconds * 1000);
        return () => {
            if (pollRef.current) clearInterval(pollRef.current);
        };
    }, [isConnected, refreshSeconds, refreshRunStates, refreshJobStats, refreshModules]);

    const handleRefreshAll = useCallback(() => {
        refreshRunStates();
        refreshJobStats();
        refreshModules();
        refreshSchedules();
    }, [refreshRunStates, refreshJobStats, refreshModules, refreshSchedules]);

    const handleCancel = useCallback(
        async (moduleName, jobId) => {
            try {
                await modulesAPI.cancelExecution(moduleName, jobId);
                toast.info(`Cancellation requested for ${humanize(moduleName)}`);
                refreshRunStates();
            } catch (err) {
                toast.error(`Failed to cancel: ${err.message}`);
            }
        },
        [refreshRunStates, toast]
    );

    const handleRunNow = useCallback(
        async moduleName => {
            try {
                await modulesAPI.executeModule(moduleName);
                toast.info(`${humanize(moduleName)} queued`);
                refreshRunStates();
                refreshJobStats();
            } catch (err) {
                toast.error(`Failed to run: ${err.message}`);
            }
        },
        [refreshRunStates, refreshJobStats, toast]
    );

    const isLoading = runStatesLoading || jobsLoading || modulesLoading || scheduleLoading;

    const runStates = useMemo(() => runStatesData?.data || {}, [runStatesData]);

    const jobStats = useMemo(() => {
        const counts = jobStatsData?.data?.status_counts || {};
        return {
            pending: counts.pending || 0,
            running: counts.running || 0,
            completed: counts.success || 0,
            failed: counts.error || 0,
        };
    }, [jobStatsData]);

    const schedules = useMemo(() => scheduleData?.data?.schedule || {}, [scheduleData]);
    // Server-computed next-run timestamps for cron(...) modules — the frontend
    // can't parse cron, so it leans on these for the "Upcoming" list.
    const nextRuns = useMemo(() => scheduleData?.data?.next_runs || {}, [scheduleData]);
    // Per-instance Upgradinatorr sub-schedules (read-only here).
    const subSchedules = useMemo(() => scheduleData?.data?.sub_schedules || [], [scheduleData]);
    // Grouped by module key so each module status card can list its own.
    const subSchedulesByModule = useMemo(() => {
        const grouped = {};
        for (const sub of subSchedules) {
            (grouped[sub.module] ||= []).push(sub);
        }
        return grouped;
    }, [subSchedules]);
    // Multi-block schedules (config.schedule_blocks): module -> [blocks]. These
    // render as gold "block" sub-rows; per-instance profiles (above) render as
    // cyan "profile" sub-rows. A sub_schedules entry is a block when its label
    // matches one of the module's schedule_blocks; everything else is a profile.
    const scheduleBlocks = useMemo(() => scheduleData?.data?.schedule_blocks || {}, [scheduleData]);
    const subRowsByModule = useMemo(() => {
        const out = {};
        const names = new Set([
            ...Object.keys(subSchedulesByModule),
            ...Object.keys(scheduleBlocks),
        ]);
        for (const name of names) {
            const blocks = scheduleBlocks[name] || [];
            const blockLabels = new Set(blocks.map(b => b.label));
            const profiles = (subSchedulesByModule[name] || []).filter(
                s => !blockLabels.has(s.label)
            );
            out[name] = [
                ...profiles.map(p => ({ ...p, kind: 'profile' })),
                ...blocks.map(b => ({ ...b, module: name, kind: 'block' })),
            ];
        }
        return out;
    }, [subSchedulesByModule, scheduleBlocks]);

    const moduleList = useMemo(() => modulesData?.data?.modules || [], [modulesData]);
    const moduleCount = moduleList.length;

    // User-chosen subset (general.dashboard_modules) controls which module
    // cards render and in what order. Empty = show all. Keys that no longer
    // map to a live module are skipped. Scheduler counts below stay on the
    // full moduleList — this only narrows the Modules grid.
    const dashboardModuleKeys = useMemo(() => dashboardCfg.dashboard_modules || [], [dashboardCfg]);
    const visibleModules = useMemo(() => {
        if (!dashboardModuleKeys.length) return moduleList;
        const byName = new Map(moduleList.map(m => [m.name, m]));
        return dashboardModuleKeys.map(k => byName.get(k)).filter(Boolean);
    }, [moduleList, dashboardModuleKeys]);
    const scheduledCount = useMemo(
        () =>
            Object.values(schedules).filter(v => v && v.trim()).length +
            subSchedules.filter(s => s.enabled && s.schedule && s.schedule.trim()).length,
        [schedules, subSchedules]
    );
    const runningCount = useMemo(() => moduleList.filter(m => m.running).length, [moduleList]);

    const diskMounts = useMemo(() => {
        // Unraid bind-mounts commonly share the same underlying device (e.g.
        // /config, /kometa, /plex all on /mnt/cache). Collapse those into a
        // single card that lists every path sharing the device so the user
        // doesn't see the same 1060 GB repeated three times.
        const mounts = diskData?.data?.mounts || diskData?.mounts || [];
        const existing = Array.isArray(mounts) ? mounts.filter(m => m.exists) : [];
        const byDevice = new Map();
        const orderless = [];
        for (const m of existing) {
            const key = m.device_id ?? `path:${m.path}`;
            if (!byDevice.has(key)) {
                byDevice.set(key, { ...m, paths: [m.path] });
                orderless.push(key);
            } else {
                byDevice.get(key).paths.push(m.path);
            }
        }
        return orderless.map(k => byDevice.get(k));
    }, [diskData]);

    const posterStats = useMemo(() => {
        const s = posterStatsData?.data || {};
        return {
            cached: s.poster_cache_count ?? 0,
        };
    }, [posterStatsData]);

    const lastFailure = useMemo(() => {
        const list = lastFailureData?.data?.jobs || lastFailureData?.data || [];
        const job = Array.isArray(list) ? list[0] : null;
        if (!job) return null;
        const moduleName = job.module_name || job.module || job.job_type || 'job';
        const ts = job.completed_at || job.updated_at || job.received_at || job.created_at;
        return { moduleName, ts };
    }, [lastFailureData]);

    const instanceHealth = useMemo(() => {
        // Combine configured-instances state (from /api/instances) with the
        // scheduler's periodic reachability snapshots (system_health_snapshots).
        // The static config tells us how many instances exist and which are
        // enabled; the snapshots tell us which were actually reachable in the
        // last probe and what the 7-day uptime % looks like.
        const byType = instancesRaw?.data || instancesRaw || {};
        let total = 0;
        let enabled = 0;
        const enabledNames = new Set();
        for (const typeName of ['radarr', 'sonarr', 'lidarr', 'plex']) {
            const bucket = byType[typeName] || {};
            if (bucket && typeof bucket === 'object') {
                for (const [name, entry] of Object.entries(bucket)) {
                    total += 1;
                    if (entry && entry.enabled !== false) {
                        enabled += 1;
                        enabledNames.add(name);
                    }
                }
            }
        }

        const snapshots = healthSnapshotsData?.data?.snapshots || [];
        const latestByInstance = new Map();
        const samplesByInstance = new Map();
        for (const snap of snapshots) {
            const name = snap.instance_name;
            if (!enabledNames.has(name)) continue;
            if (!latestByInstance.has(name)) latestByInstance.set(name, snap);
            const bucket = samplesByInstance.get(name) || { ok: 0, total: 0 };
            bucket.total += 1;
            if (snap.status === 'healthy') bucket.ok += 1;
            samplesByInstance.set(name, bucket);
        }

        let reachable = 0;
        let probedCount = 0;
        let uptimeNumerator = 0;
        let uptimeDenominator = 0;
        for (const name of enabledNames) {
            const latest = latestByInstance.get(name);
            if (latest) {
                probedCount += 1;
                if (latest.status === 'healthy') reachable += 1;
            }
            const samples = samplesByInstance.get(name);
            if (samples) {
                uptimeNumerator += samples.ok;
                uptimeDenominator += samples.total;
            }
        }

        const uptimePct =
            uptimeDenominator > 0 ? Math.round((uptimeNumerator / uptimeDenominator) * 100) : null;

        return { total, enabled, reachable, probedCount, uptimePct };
    }, [instancesRaw, healthSnapshotsData]);

    const upcomingRuns = useMemo(() => {
        const now = new Date(tick);
        const entries = [];
        // Parse a server-supplied ISO next-run, guarding against bad values.
        const parseIso = iso => {
            if (!iso) return null;
            const d = new Date(iso);
            return Number.isNaN(d.getTime()) ? null : d;
        };
        for (const [moduleName, expr] of Object.entries(schedules)) {
            if (!expr || !expr.trim()) continue;
            // Fall back to the server's cron next-run when the client can't parse it.
            const next = scheduleToNextFire(expr, now) || parseIso(nextRuns[moduleName]);
            if (!next) continue;
            entries.push({
                id: moduleName,
                module: moduleName,
                label: humanize(moduleName),
                schedule: expr,
                next,
            });
        }
        // Per-instance Upgradinatorr sub-schedules ride alongside the modules.
        for (const sub of subSchedules) {
            if (!sub.enabled || !sub.schedule || !sub.schedule.trim()) continue;
            const next = scheduleToNextFire(sub.schedule, now) || parseIso(sub.next_run);
            if (!next) continue;
            entries.push({
                id: `${sub.module}:${sub.label}`,
                module: sub.module,
                label: `${humanize(sub.module)} · ${sub.label}`,
                schedule: sub.schedule,
                next,
            });
        }
        entries.sort((a, b) => a.next.getTime() - b.next.getTime());
        return entries.slice(0, upcomingLimit);
    }, [schedules, nextRuns, subSchedules, tick, upcomingLimit]);

    // Currently-running modules ride at the top of the "Up next" rail (with a
    // pulsing dot + indeterminate bar) ahead of the scheduled entries.
    const runningModules = useMemo(
        () => moduleList.filter(m => m.running || runStates[m.name]?.status === 'running'),
        [moduleList, runStates]
    );
    const upNext = useMemo(() => {
        const running = runningModules.map(m => ({
            id: `run:${m.name}`,
            label: humanize(m.name),
            running: true,
        }));
        return [...running, ...upcomingRuns.map(e => ({ ...e, running: false }))].slice(
            0,
            Math.max(upcomingLimit, running.length)
        );
    }, [runningModules, upcomingRuns, upcomingLimit]);

    if (isLoading && moduleList.length === 0) {
        // Skeleton placeholders for the module-card grid + health row so the
        // page doesn't pop-flicker as the run-states / jobs / modules /
        // schedule / instances / posters / snapshots calls each resolve.
        return (
            <div className="flex flex-col gap-10" aria-busy="true">
                <section className="flex items-center justify-between gap-4">
                    <Skeleton width="60%" height="2.5rem" rounded="md" />
                    <Skeleton width="6rem" height="2rem" rounded="full" />
                </section>
                <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {Array.from({ length: 6 }).map((_, i) => (
                        <Skeleton key={i} height="6.5rem" rounded="lg" />
                    ))}
                </section>
                <section className="grid grid-cols-auto-fit-xs md:grid-cols-2 lg:grid-cols-4 gap-3">
                    {Array.from({ length: 4 }).map((_, i) => (
                        <Skeleton key={i} height="5rem" rounded="lg" />
                    ))}
                </section>
            </div>
        );
    }

    const schedulerStateLabel =
        runningCount > 0 ? `${runningCount} running` : scheduledCount > 0 ? 'Active' : 'Idle';

    return (
        <div className="flex flex-col gap-5">
            {/* Toolbar */}
            <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="min-w-0">
                    <h1 className="font-display text-[26px] font-bold tracking-[-0.3px] text-fg m-0">
                        Dashboard
                    </h1>
                    <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">
                        {moduleCount} modules · {instanceHealth.total} instances ·{' '}
                        <span
                            className="font-mono text-fg-muted"
                            title={isConnected ? 'Live updates via SSE' : 'Polling for updates'}
                        >
                            {isConnected ? 'live' : 'polling'}
                        </span>
                    </p>
                </div>
                <div className="flex items-center gap-2.5">
                    <button
                        type="button"
                        onClick={handleRefreshAll}
                        className="inline-flex items-center gap-1.5 h-[38px] px-3.5 rounded-lg bg-surface border border-border text-fg-muted text-[13.5px] font-medium hover:bg-surface-elevated transition-colors"
                    >
                        <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
                            refresh
                        </span>
                        Refresh
                    </button>
                    <button
                        ref={newRunRef}
                        type="button"
                        onClick={() => setNewRunOpen(o => !o)}
                        className="inline-flex items-center gap-1.5 h-[38px] px-4 rounded-lg bg-primary text-on-color font-display text-[13.5px] font-semibold hover:brightness-110 transition"
                        style={{ boxShadow: '0 4px 16px -5px var(--primary)' }}
                    >
                        <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
                            add
                        </span>
                        New run
                    </button>
                    <Dropdown
                        isOpen={newRunOpen}
                        onClose={() => setNewRunOpen(false)}
                        anchorRef={newRunRef}
                        placement="bottom-right"
                    >
                        <div className="max-h-72 overflow-y-auto">
                            {moduleList.map(m => (
                                <button
                                    key={m.name}
                                    type="button"
                                    onClick={() => {
                                        setNewRunOpen(false);
                                        setRunNowTarget(m.name);
                                    }}
                                    className="w-full text-left px-3 py-2 rounded-md text-sm text-fg hover:bg-row-hover transition-colors"
                                >
                                    {humanize(m.name)}
                                </button>
                            ))}
                        </div>
                    </Dropdown>
                </div>
            </div>

            {/* Status strip — scheduler / running / pending / failed / instances
                / last-failure. Mono labels + mono values. */}
            <div
                className="flex items-stretch flex-wrap bg-surface border border-border rounded-xl overflow-hidden"
                style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
            >
                {(() => {
                    const instTone =
                        instanceHealth.probedCount > 0
                            ? instanceHealth.reachable === instanceHealth.probedCount
                                ? 'text-success'
                                : instanceHealth.reachable === 0
                                  ? 'text-error'
                                  : 'text-warning'
                            : instanceHealth.enabled === instanceHealth.total
                              ? 'text-success'
                              : 'text-warning';
                    const instValue =
                        instanceHealth.probedCount > 0
                            ? `${instanceHealth.reachable}/${instanceHealth.probedCount}`
                            : `${instanceHealth.enabled}/${instanceHealth.total}`;
                    const cells = [
                        {
                            label: 'SCHEDULER',
                            grow: 1.3,
                            node: (
                                <span className="flex items-center gap-2 font-display font-semibold text-[16px] text-fg">
                                    <StatusDot
                                        status={
                                            runningCount > 0
                                                ? 'running'
                                                : scheduledCount > 0
                                                  ? 'success'
                                                  : 'idle'
                                        }
                                        size={8}
                                    />
                                    {schedulerStateLabel}
                                </span>
                            ),
                        },
                        {
                            label: 'RUNNING',
                            value: runningCount,
                            tone: runningCount > 0 ? 'text-accent' : 'text-fg-muted',
                        },
                        { label: 'PENDING', value: jobStats.pending, tone: 'text-fg-muted' },
                        {
                            label: 'FAILED',
                            value: jobStats.failed,
                            tone: jobStats.failed > 0 ? 'text-error' : 'text-fg-dim',
                        },
                        { label: 'INSTANCES', value: instValue, tone: instTone },
                        {
                            label: 'LAST FAILURE',
                            grow: 1.2,
                            node: (
                                <Link
                                    to={
                                        lastFailure
                                            ? `/logs?module=${encodeURIComponent(lastFailure.moduleName)}`
                                            : '/settings/jobs'
                                    }
                                    className={`font-medium text-[15px] no-underline truncate ${lastFailure ? 'text-error' : 'text-fg-muted'}`}
                                    title={
                                        lastFailure?.ts ? formatDateTime(lastFailure.ts) : undefined
                                    }
                                >
                                    {lastFailure
                                        ? formatTimeAgo(lastFailure.ts, new Date(tick))
                                        : 'None'}
                                </Link>
                            ),
                        },
                    ];
                    return cells.map((c, i) => (
                        <React.Fragment key={c.label}>
                            {i > 0 && <div className="w-px self-stretch bg-border my-3" />}
                            <div
                                className="px-[22px] py-3.5 flex flex-col gap-1.5 min-w-0"
                                style={{ flex: c.grow || 1 }}
                            >
                                <span className="font-mono text-[10px] tracking-[1.2px] text-fg-subtle">
                                    {c.label}
                                </span>
                                {c.node || (
                                    <span
                                        className={`font-mono font-semibold text-[18px] ${c.tone}`}
                                    >
                                        {c.value}
                                    </span>
                                )}
                            </div>
                        </React.Fragment>
                    ));
                })()}
            </div>

            {/* Modules table + right rail (Up next / Storage) */}
            <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-5 items-start">
                <section
                    className="bg-surface border border-border rounded-xl overflow-hidden"
                    style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
                >
                    <div className="flex items-center justify-between px-5 pt-4 pb-3.5">
                        <div>
                            <h2 className="font-display text-[15px] font-semibold text-fg m-0">
                                Modules
                            </h2>
                            <p className="text-fg-subtle text-xs mt-0.5 mb-0">
                                Live status of every configured module
                            </p>
                        </div>
                        <Link
                            to="/logs"
                            className="text-[12.5px] text-accent no-underline font-medium hover:underline whitespace-nowrap"
                        >
                            All logs →
                        </Link>
                    </div>
                    <div className="overflow-x-auto">
                        <div className="min-w-[620px]">
                            <div className="grid grid-cols-[1.7fr_1.5fr_0.9fr_1.3fr_86px] gap-3 px-5 py-2 border-y border-border font-mono text-[10px] tracking-[1px] text-fg-faint">
                                <span>MODULE</span>
                                <span>SCHEDULE</span>
                                <span>LAST</span>
                                <span>NEXT</span>
                                <span className="text-right">ACTION</span>
                            </div>
                            {visibleModules.map(mod => {
                                const state = runStates[mod.name];
                                const lastRun = mod.last_run || state?.last_run;
                                // Live run-state wins over the persisted last-run status so an
                                // in-progress job isn't hidden by a stale completed status.
                                const lastStatus = state?.status || mod.last_run_status;
                                const schedule = mod.schedule;
                                const subRows = subRowsByModule[mod.name] || [];
                                const expandable = subRows.length > 0;
                                const isOpen = expandable && !!expandedRows[mod.name];
                                const jobId = state?.job_id;
                                const isRunning = lastStatus === 'running';
                                const dotStatus = isRunning
                                    ? 'running'
                                    : lastStatus === 'error'
                                      ? 'error'
                                      : lastStatus === 'success'
                                        ? 'success'
                                        : 'idle';
                                const auto = !!schedule;
                                const upc = upcomingRuns.find(e => e.id === mod.name);
                                const nextText = isRunning
                                    ? 'running…'
                                    : upc
                                      ? formatTimeUntil(upc.next, new Date(tick))
                                      : '—';
                                const nextTone = isRunning
                                    ? 'text-accent'
                                    : nextText === '—'
                                      ? 'text-fg-dim'
                                      : 'text-fg-muted';
                                return (
                                    <React.Fragment key={mod.name}>
                                        <div
                                            className={`grid grid-cols-[1.7fr_1.5fr_0.9fr_1.3fr_86px] gap-3 items-center px-5 py-3.5 border-b border-border-light transition-colors ${expandable ? 'cursor-pointer hover:bg-row-hover' : ''}`}
                                            onClick={
                                                expandable ? () => toggleRow(mod.name) : undefined
                                            }
                                        >
                                            <div className="flex items-center gap-2 min-w-0">
                                                <span
                                                    className="w-3 flex items-center justify-center text-fg-subtle transition-transform"
                                                    style={{
                                                        visibility: expandable
                                                            ? 'visible'
                                                            : 'hidden',
                                                        transform: isOpen
                                                            ? 'rotate(90deg)'
                                                            : 'rotate(0deg)',
                                                    }}
                                                    aria-hidden="true"
                                                >
                                                    <span className="material-symbols-outlined text-[16px]">
                                                        chevron_right
                                                    </span>
                                                </span>
                                                <StatusDot status={dotStatus} />
                                                <Link
                                                    to={`/logs?module=${encodeURIComponent(mod.name)}`}
                                                    onClick={e => e.stopPropagation()}
                                                    className="min-w-0 no-underline"
                                                >
                                                    <div className="font-semibold text-[13.5px] text-fg truncate hover:text-accent">
                                                        {humanize(mod.name)}
                                                    </div>
                                                    <div
                                                        className="font-mono text-[9.5px] tracking-[0.5px] mt-0.5"
                                                        style={{
                                                            color: auto
                                                                ? 'var(--primary)'
                                                                : 'var(--manual)',
                                                        }}
                                                    >
                                                        {auto ? 'AUTO' : 'MANUAL'}
                                                    </div>
                                                </Link>
                                            </div>
                                            <div className="font-mono text-xs text-fg-muted truncate">
                                                {schedule ? scheduleToHuman(schedule) : 'Manual'}
                                            </div>
                                            <div className="font-mono text-xs text-fg-subtle truncate">
                                                {lastRun
                                                    ? formatTimeAgo(lastRun, new Date(tick))
                                                    : '—'}
                                            </div>
                                            <div
                                                className={`font-mono text-xs truncate ${nextTone}`}
                                            >
                                                {nextText}
                                            </div>
                                            <div
                                                className="flex justify-end"
                                                onClick={e => e.stopPropagation()}
                                            >
                                                {isRunning && jobId ? (
                                                    <button
                                                        type="button"
                                                        onClick={() =>
                                                            handleCancel(mod.name, jobId)
                                                        }
                                                        className="h-[30px] px-3 rounded-[7px] bg-surface-inset border border-border text-accent text-xs font-semibold hover:bg-row-hover transition-colors"
                                                        title="Cancel run"
                                                    >
                                                        Running
                                                    </button>
                                                ) : (
                                                    <button
                                                        type="button"
                                                        onClick={() => setRunNowTarget(mod.name)}
                                                        className="h-[30px] px-3 rounded-[7px] bg-surface-inset border border-border text-fg-muted text-xs font-semibold hover:bg-row-hover transition-colors"
                                                    >
                                                        Run
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                        {isOpen &&
                                            subRows.map(sub => {
                                                const en = sub.enabled !== false;
                                                const isProfile = sub.kind === 'profile';
                                                const pillColor = isProfile
                                                    ? 'var(--source-gdrive)'
                                                    : 'var(--warning)';
                                                const pillBg = isProfile
                                                    ? 'rgba(83,232,240,.12)'
                                                    : 'rgba(255,201,68,.12)';
                                                const nf = en
                                                    ? scheduleToNextFire(
                                                          sub.schedule,
                                                          new Date(tick)
                                                      ) ||
                                                      (sub.next_run ? new Date(sub.next_run) : null)
                                                    : null;
                                                const subNext = !en
                                                    ? 'paused'
                                                    : nf
                                                      ? formatTimeUntil(nf, new Date(tick))
                                                      : '—';
                                                const overrideKeys =
                                                    sub.kind === 'block' && sub.overrides
                                                        ? Object.keys(sub.overrides)
                                                        : [];
                                                return (
                                                    <div
                                                        key={`${mod.name}:${sub.kind}:${sub.label}`}
                                                        className="grid grid-cols-[1.7fr_1.5fr_0.9fr_1.3fr_86px] gap-3 items-center px-5 py-2.5 bg-surface-inset border-b border-border-light"
                                                        style={{
                                                            boxShadow:
                                                                'inset 3px 0 0 var(--primary)',
                                                            opacity: en ? 1 : 0.5,
                                                        }}
                                                    >
                                                        <div className="flex items-center gap-2 min-w-0 pl-7">
                                                            <span
                                                                className="w-1.5 h-1.5 rounded-full shrink-0"
                                                                style={{ background: pillColor }}
                                                                aria-hidden="true"
                                                            />
                                                            <span className="text-[12.5px] font-medium text-fg-muted truncate">
                                                                {sub.label}
                                                            </span>
                                                            <span
                                                                className="shrink-0 font-mono text-[8.5px] tracking-[0.4px] uppercase px-1.5 py-px rounded-[5px]"
                                                                style={{
                                                                    color: pillColor,
                                                                    background: pillBg,
                                                                }}
                                                            >
                                                                {sub.kind}
                                                            </span>
                                                        </div>
                                                        <div className="font-mono text-[11.5px] text-fg-data truncate">
                                                            {scheduleToHuman(sub.schedule)}
                                                        </div>
                                                        <div className="font-mono text-[10.5px] text-fg-subtle truncate">
                                                            {overrideKeys.join(', ')}
                                                        </div>
                                                        <div
                                                            className={`font-mono text-[11.5px] truncate ${en ? 'text-fg-muted' : 'text-fg-dim'}`}
                                                        >
                                                            {subNext}
                                                        </div>
                                                        <div className="flex justify-end" />
                                                    </div>
                                                );
                                            })}
                                    </React.Fragment>
                                );
                            })}
                        </div>
                    </div>
                </section>

                {/* Right rail */}
                <div className="flex flex-col gap-5">
                    {/* Up next */}
                    <section
                        className="bg-surface border border-border rounded-xl p-[18px]"
                        style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
                    >
                        <div className="flex items-center justify-between mb-3.5">
                            <h2 className="font-display text-[15px] font-semibold text-fg m-0">
                                Up next
                            </h2>
                            <Link
                                to="/settings/schedule"
                                className="text-xs text-accent no-underline hover:underline"
                            >
                                Manage
                            </Link>
                        </div>
                        {upNext.length === 0 ? (
                            <div className="text-sm text-fg-subtle italic py-2">
                                No scheduled runs coming up.
                            </div>
                        ) : (
                            (() => {
                                const firstUpcoming = upNext.findIndex(e => !e.running);
                                return (
                                    <ul className="flex flex-col m-0 p-0 list-none">
                                        {upNext.map((entry, i) => (
                                            <li
                                                key={entry.id}
                                                className={`flex gap-3 py-3 ${i < upNext.length - 1 ? 'border-b border-border-light' : ''}`}
                                            >
                                                {entry.running ? (
                                                    <span
                                                        className="shrink-0 w-[9px] h-[9px] rounded-full bg-accent mt-1"
                                                        style={{
                                                            boxShadow:
                                                                '0 0 0 3px rgba(83,232,240,.18)',
                                                            animation:
                                                                'chub-pulse 1.4s ease-in-out infinite',
                                                        }}
                                                        aria-hidden="true"
                                                    />
                                                ) : (
                                                    <span
                                                        className="shrink-0 w-[9px] h-[9px] rounded-full mt-1"
                                                        style={
                                                            i === firstUpcoming
                                                                ? {
                                                                      background: '#110b28',
                                                                      border: '2px solid #ffc944',
                                                                  }
                                                                : {
                                                                      background: '#1d1942',
                                                                      border: '2px solid #3b3d72',
                                                                  }
                                                        }
                                                        aria-hidden="true"
                                                    />
                                                )}
                                                <div className="flex-1 min-w-0">
                                                    <div className="flex justify-between gap-2">
                                                        <span className="font-semibold text-[13.5px] text-fg truncate">
                                                            {entry.label}
                                                        </span>
                                                        <span
                                                            className="font-mono text-[11.5px] shrink-0"
                                                            style={{
                                                                color: entry.running
                                                                    ? '#53e8f0'
                                                                    : i === firstUpcoming
                                                                      ? '#ffc944'
                                                                      : '#b2d1e8',
                                                            }}
                                                        >
                                                            {entry.running
                                                                ? 'running'
                                                                : formatTimeUntil(
                                                                      entry.next,
                                                                      new Date(tick)
                                                                  )}
                                                        </span>
                                                    </div>
                                                    {entry.running ? (
                                                        <div className="h-1 rounded-[3px] bg-border mt-2 overflow-hidden">
                                                            <div
                                                                className="h-full w-1/3 rounded-[3px] bg-accent"
                                                                style={{
                                                                    animation:
                                                                        'chub-indeterminate 1.4s ease-in-out infinite',
                                                                }}
                                                            />
                                                        </div>
                                                    ) : (
                                                        <div className="font-mono text-[11px] text-fg-subtle mt-1 truncate">
                                                            {entry.next.toLocaleTimeString([], {
                                                                hour: '2-digit',
                                                                minute: '2-digit',
                                                            })}{' '}
                                                            · {scheduleToHuman(entry.schedule)}
                                                        </div>
                                                    )}
                                                </div>
                                            </li>
                                        ))}
                                    </ul>
                                );
                            })()
                        )}
                    </section>

                    {/* Storage */}
                    {diskMounts.length > 0 && (
                        <section
                            className="bg-surface border border-border rounded-xl p-[18px]"
                            style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
                        >
                            <div className="flex items-baseline justify-between mb-4">
                                <h2 className="font-display text-[15px] font-semibold text-fg m-0">
                                    Storage
                                </h2>
                                {posterStats.cached > 0 && (
                                    <span className="font-mono text-[11px] text-fg-subtle">
                                        {posterStats.cached.toLocaleString()} posters cached
                                    </span>
                                )}
                            </div>
                            <div className="flex flex-col gap-4">
                                {diskMounts.map(mount => {
                                    const freeGb = mount.free_bytes / 1024 ** 3;
                                    const totalGb = mount.total_bytes / 1024 ** 3;
                                    const pct = mount.percent_used ?? 0;
                                    const paths = mount.paths || [mount.path];
                                    const high = pct >= 90;
                                    const warn = pct >= 75;
                                    const pctColor = high
                                        ? '#fd355c'
                                        : warn
                                          ? '#ffc944'
                                          : '#6cbc66';
                                    const barBg = high
                                        ? '#fd355c'
                                        : warn
                                          ? 'linear-gradient(90deg,#e28b2d,#ffc944)'
                                          : '#6cbc66';
                                    const fmt = v =>
                                        v >= 1024
                                            ? `${(v / 1024).toFixed(2)} TB`
                                            : `${v.toFixed(1)} GB`;
                                    return (
                                        <div key={paths.join('|')}>
                                            <div className="flex justify-between items-baseline mb-1.5">
                                                <span
                                                    className="font-mono text-[11px] tracking-[0.5px] text-fg-muted truncate"
                                                    title={paths.join(', ')}
                                                >
                                                    {paths.join(' · ')}
                                                </span>
                                                <span
                                                    className="font-mono text-[11.5px] shrink-0"
                                                    style={{ color: pctColor }}
                                                >
                                                    {pct}%
                                                </span>
                                            </div>
                                            <div className="h-[7px] rounded-[4px] bg-border overflow-hidden">
                                                <div
                                                    className="h-full rounded-[4px]"
                                                    style={{
                                                        width: `${Math.min(pct, 100)}%`,
                                                        background: barBg,
                                                    }}
                                                />
                                            </div>
                                            <div className="font-mono text-[10.5px] text-fg-subtle mt-1.5">
                                                {fmt(freeGb)} free of {fmt(totalGb)}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </section>
                    )}
                </div>
            </div>

            {/* Run-now confirmation */}
            <Modal isOpen={!!runNowTarget} onClose={() => setRunNowTarget(null)} size="small">
                <Modal.Header>Run {runNowTarget ? humanize(runNowTarget) : ''}?</Modal.Header>
                <Modal.Body>
                    <p className="text-fg-muted">
                        Queue{' '}
                        <span className="font-semibold text-fg">
                            {runNowTarget ? humanize(runNowTarget) : ''}
                        </span>{' '}
                        for an immediate run. The module will execute with its currently saved
                        configuration. Progress shows up in Logs.
                    </p>
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="ghost" onClick={() => setRunNowTarget(null)}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        icon="play_arrow"
                        onClick={() => {
                            const name = runNowTarget;
                            setRunNowTarget(null);
                            if (name) handleRunNow(name);
                        }}
                    >
                        Run now
                    </Button>
                </Modal.Footer>
            </Modal>
        </div>
    );
};

export default DashboardPage;
