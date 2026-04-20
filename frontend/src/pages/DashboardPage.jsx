import React, { useMemo, useEffect, useRef, useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { useApiData } from '../hooks/useApiData';
import { useModuleEvents } from '../hooks/useModuleEvents';
import { modulesAPI } from '../utils/api/modules';
import { jobsAPI } from '../utils/api/jobs';
import { systemAPI } from '../utils/api/system';
import { scheduleAPI } from '../utils/api/schedule';
import { IconButton } from '../components/ui';
import Spinner from '../components/ui/Spinner';
import { useAuth } from '../contexts/AuthContext.jsx';
import { useToast } from '../contexts/ToastContext.jsx';
import { humanize } from '../utils/tools.js';
import {
    scheduleToNextFire,
    scheduleToHuman,
    formatTimeUntil,
    formatTimeAgo,
} from '../utils/schedule.js';

const POLL_INTERVAL = 30000;
const UPCOMING_LIMIT = 5;
const RECENT_JOB_LIMIT = 8;

const QUICK_START = [
    {
        id: 'run-module',
        title: 'Run a module',
        description: 'Kick off any configured module on demand.',
        icon: 'play_arrow',
        badge: 1,
        to: '/settings/modules',
    },
    {
        id: 'browse-media',
        title: 'Browse media',
        description: 'Search and manage your Radarr / Sonarr library.',
        icon: 'movie',
        badge: 2,
        to: '/media/search',
    },
    {
        id: 'browse-posters',
        title: 'Browse posters',
        description: 'Explore GDrive and local asset libraries.',
        icon: 'image',
        badge: 3,
        to: '/poster/search/assets',
    },
    {
        id: 'duplicates',
        title: 'Find duplicates',
        description: 'Resolve duplicate media across instances.',
        icon: 'content_copy',
        badge: 4,
        to: '/media/manage',
    },
    {
        id: 'logs',
        title: 'Inspect logs',
        description: 'Tail module runs and diagnose failures.',
        icon: 'description',
        badge: 5,
        to: '/logs',
    },
    {
        id: 'webhooks',
        title: 'Webhooks',
        description: 'Trigger cleanup and unmatched asset flows.',
        icon: 'webhook',
        badge: 1,
        to: '/settings/webhooks',
    },
];

const listRecentJobs = (options = {}) => jobsAPI.listJobs({ limit: RECENT_JOB_LIMIT }, options);

const statusPillClass = status => {
    switch (status) {
        case 'success':
            return 'bg-success/20 text-success';
        case 'error':
            return 'bg-error/20 text-error';
        case 'running':
            return 'bg-primary/20 text-primary';
        case 'pending':
            return 'bg-warning/20 text-warning';
        default:
            return 'bg-surface-alt text-secondary';
    }
};

const jobDuration = job => {
    const start = job.started_at || job.received_at;
    const end = job.completed_at;
    if (!start || !end) return null;
    const ms = new Date(end).getTime() - new Date(start).getTime();
    if (ms < 0) return null;
    const seconds = Math.round(ms / 1000);
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${minutes}m ${secs}s`;
};

const DashboardPage = () => {
    const toast = useToast();
    const { user } = useAuth();
    const [tick, setTick] = useState(() => Date.now());

    useEffect(() => {
        const id = setInterval(() => setTick(Date.now()), 30000);
        return () => clearInterval(id);
    }, []);

    const { data: versionData } = useApiData({
        apiFunction: systemAPI.getVersion,
        options: { showErrorToast: false },
    });

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

    const {
        data: recentJobsData,
        isLoading: recentJobsLoading,
        refresh: refreshRecentJobs,
    } = useApiData({
        apiFunction: listRecentJobs,
        options: { showErrorToast: false },
    });

    const handleStatusChange = useCallback(() => {
        refreshRunStates();
        refreshJobStats();
        refreshRecentJobs();
    }, [refreshRunStates, refreshJobStats, refreshRecentJobs]);

    const { isConnected } = useModuleEvents({ onStatusChange: handleStatusChange });

    const pollRef = useRef(null);
    useEffect(() => {
        if (isConnected) {
            if (pollRef.current) clearInterval(pollRef.current);
            return;
        }
        pollRef.current = setInterval(() => {
            refreshRunStates();
            refreshJobStats();
            refreshModules();
            refreshRecentJobs();
        }, POLL_INTERVAL);
        return () => {
            if (pollRef.current) clearInterval(pollRef.current);
        };
    }, [isConnected, refreshRunStates, refreshJobStats, refreshModules, refreshRecentJobs]);

    const handleRefreshAll = useCallback(() => {
        refreshRunStates();
        refreshJobStats();
        refreshModules();
        refreshSchedules();
        refreshRecentJobs();
    }, [refreshRunStates, refreshJobStats, refreshModules, refreshSchedules, refreshRecentJobs]);

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

    const isLoading =
        runStatesLoading || jobsLoading || modulesLoading || scheduleLoading || recentJobsLoading;

    const version = useMemo(() => {
        if (!versionData) return null;
        if (typeof versionData === 'string') return versionData;
        return versionData?.data?.version || versionData?.data || versionData;
    }, [versionData]);

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
    const moduleList = useMemo(() => modulesData?.data?.modules || [], [modulesData]);
    const moduleCount = moduleList.length;
    const scheduledCount = useMemo(
        () => Object.values(schedules).filter(v => v && v.trim()).length,
        [schedules]
    );
    const runningCount = useMemo(() => moduleList.filter(m => m.running).length, [moduleList]);

    const upcomingRuns = useMemo(() => {
        const now = new Date(tick);
        const entries = [];
        for (const [moduleName, expr] of Object.entries(schedules)) {
            if (!expr || !expr.trim()) continue;
            const next = scheduleToNextFire(expr, now);
            if (!next) continue;
            entries.push({
                module: moduleName,
                schedule: expr,
                next,
            });
        }
        entries.sort((a, b) => a.next.getTime() - b.next.getTime());
        return entries.slice(0, UPCOMING_LIMIT);
    }, [schedules, tick]);

    const recentJobs = useMemo(() => {
        const jobs = recentJobsData?.data?.jobs || recentJobsData?.data || [];
        return Array.isArray(jobs) ? jobs.slice(0, RECENT_JOB_LIMIT) : [];
    }, [recentJobsData]);

    if (isLoading && moduleList.length === 0) {
        return <Spinner size="large" text="Loading dashboard..." center />;
    }

    const schedulerStateLabel =
        runningCount > 0 ? `${runningCount} running` : scheduledCount > 0 ? 'Active' : 'Idle';

    return (
        <div className="flex flex-col gap-10">
            {/* Greeting row */}
            <section className="flex flex-wrap items-center justify-between gap-4">
                <div className="min-w-0">
                    <h1 className="text-3xl md:text-4xl font-bold text-primary m-0">
                        Hello{user ? `, ${user}` : ''}!
                    </h1>
                    <p className="text-secondary mt-1 mb-0">
                        Here&apos;s what&apos;s happening across your media stack today.
                    </p>
                </div>
                <div className="flex items-center gap-3">
                    <span
                        className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full ${isConnected ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning'}`}
                        title={isConnected ? 'Live updates via SSE' : 'Polling for updates'}
                    >
                        <span
                            className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-success' : 'bg-warning'}`}
                        />
                        {isConnected ? 'Live' : 'Polling'}
                    </span>
                    <IconButton
                        icon="refresh"
                        aria-label="Refresh dashboard"
                        variant="ghost"
                        onClick={handleRefreshAll}
                    />
                    <Link
                        to="/settings/modules"
                        className="inline-flex items-center gap-2 bg-primary text-on-color no-underline rounded-lg px-4 py-2 text-sm font-medium hover:opacity-90 transition-opacity"
                    >
                        <span className="material-symbols-outlined text-base" aria-hidden="true">
                            add
                        </span>
                        <span>New run</span>
                    </Link>
                </div>
            </section>

            {/* Recent jobs — promoted to full width */}
            <section>
                <div className="flex items-end justify-between mb-4">
                    <div>
                        <h2 className="text-xl font-bold text-primary m-0">Recent jobs</h2>
                        <p className="text-secondary text-sm mt-1 mb-0">
                            The {RECENT_JOB_LIMIT} most recent module runs — click a card for logs.
                        </p>
                    </div>
                    <Link
                        to="/settings/jobs"
                        className="text-sm text-accent no-underline hover:underline"
                    >
                        View all
                    </Link>
                </div>
                {recentJobs.length === 0 ? (
                    <div className="bg-surface-alt border border-border-light rounded-lg p-6 text-sm text-tertiary text-center">
                        No jobs yet. They&apos;ll show up here once modules start running.
                    </div>
                ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                        {recentJobs.map(job => {
                            const moduleName = job.module || job.job_type || 'job';
                            const ended = job.completed_at || job.updated_at || job.created_at;
                            const status = job.status || 'success';
                            const duration = jobDuration(job);
                            return (
                                <Link
                                    key={job.id || `${moduleName}-${ended}`}
                                    to={`/logs?module=${encodeURIComponent(moduleName)}`}
                                    title={
                                        ended
                                            ? new Date(ended).toLocaleString()
                                            : 'Pending completion'
                                    }
                                    className="no-underline bg-surface border border-border-light rounded-lg p-4 flex flex-col gap-2 min-w-0 transition-transform hover:-translate-y-0.5 hover:border-border"
                                >
                                    <div className="flex items-center justify-between gap-2 min-w-0">
                                        <span className="font-semibold text-primary truncate min-w-0">
                                            {humanize(moduleName)}
                                        </span>
                                        <span
                                            className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${statusPillClass(status)}`}
                                        >
                                            {status}
                                        </span>
                                    </div>
                                    <div className="flex items-center justify-between text-xs text-tertiary">
                                        <span>
                                            {ended ? formatTimeAgo(ended, new Date(tick)) : '—'}
                                        </span>
                                        {duration && <span>{duration}</span>}
                                    </div>
                                </Link>
                            );
                        })}
                    </div>
                )}
            </section>

            {/* Scheduler — full-width panel */}
            <section className="bg-surface-alt border border-border-light rounded-lg p-6 flex flex-col gap-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-3 min-w-0">
                        <span
                            className="badge-bubble badge-bubble--3 w-11 h-11 rounded-full flex items-center justify-center shrink-0"
                            aria-hidden="true"
                        >
                            <span className="material-symbols-outlined">schedule</span>
                        </span>
                        <div className="min-w-0">
                            <div className="text-xs font-semibold uppercase tracking-wider text-tertiary">
                                Scheduler
                            </div>
                            <div className="text-lg font-bold text-primary">
                                {schedulerStateLabel}
                            </div>
                        </div>
                    </div>
                    <Link
                        to="/settings/schedule"
                        className="text-sm text-accent no-underline hover:underline"
                    >
                        Manage schedules
                    </Link>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-sm">
                    <div className="bg-surface rounded-lg px-3 py-2">
                        <div className="text-tertiary text-xs">Modules</div>
                        <div className="font-semibold text-primary">{moduleCount}</div>
                    </div>
                    <div className="bg-surface rounded-lg px-3 py-2">
                        <div className="text-tertiary text-xs">Scheduled</div>
                        <div className="font-semibold text-primary">{scheduledCount}</div>
                    </div>
                    <div className="bg-surface rounded-lg px-3 py-2">
                        <div className="text-tertiary text-xs">Running</div>
                        <div className="font-semibold text-primary">{runningCount}</div>
                    </div>
                    <div className="bg-surface rounded-lg px-3 py-2">
                        <div className="text-tertiary text-xs">Pending</div>
                        <div className="font-semibold text-primary">{jobStats.pending}</div>
                    </div>
                    <div className="bg-surface rounded-lg px-3 py-2">
                        <div className="text-tertiary text-xs">Failed</div>
                        <div
                            className={`font-semibold ${jobStats.failed > 0 ? 'text-error' : 'text-primary'}`}
                        >
                            {jobStats.failed}
                        </div>
                    </div>
                </div>

                <div>
                    <div className="text-xs font-semibold uppercase tracking-wider text-tertiary mb-2">
                        Up next
                    </div>
                    {upcomingRuns.length === 0 ? (
                        <div className="text-sm text-tertiary italic">
                            No scheduled runs within the next day — cron-scheduled modules
                            aren&apos;t shown here.
                        </div>
                    ) : (
                        <ul className="flex flex-col gap-2 m-0 p-0 list-none">
                            {upcomingRuns.map(entry => (
                                <li
                                    key={entry.module}
                                    className="flex items-center justify-between gap-3 bg-surface rounded-lg px-3 py-2 text-sm"
                                >
                                    <div className="min-w-0">
                                        <div className="font-semibold text-primary truncate">
                                            {humanize(entry.module)}
                                        </div>
                                        <div className="text-xs text-tertiary truncate">
                                            {scheduleToHuman(entry.schedule)}
                                        </div>
                                    </div>
                                    <div className="text-right shrink-0">
                                        <div className="text-xs text-tertiary">
                                            {entry.next.toLocaleTimeString([], {
                                                hour: '2-digit',
                                                minute: '2-digit',
                                            })}
                                        </div>
                                        <div className="text-xs font-semibold text-accent">
                                            {formatTimeUntil(entry.next, new Date(tick))}
                                        </div>
                                    </div>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            </section>

            {/* Quick start — now below Recent jobs / Scheduler */}
            <section>
                <div className="mb-4">
                    <h2 className="text-xl font-bold text-primary m-0">Quick start</h2>
                    <p className="text-secondary text-sm mt-1 mb-0">
                        Jump straight into the things you do most.
                    </p>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {QUICK_START.map(card => (
                        <Link
                            key={card.id}
                            to={card.to}
                            className="no-underline bg-surface border border-border-light rounded-lg p-5 flex flex-col gap-3 transition-transform hover:-translate-y-0.5 hover:border-border"
                        >
                            <span
                                className={`badge-bubble badge-bubble--${card.badge} w-12 h-12 rounded-full flex items-center justify-center`}
                                aria-hidden="true"
                            >
                                <span className="material-symbols-outlined">{card.icon}</span>
                            </span>
                            <div>
                                <div className="font-semibold text-primary">{card.title}</div>
                                <div className="text-sm text-secondary mt-1">
                                    {card.description}
                                </div>
                            </div>
                        </Link>
                    ))}
                </div>
            </section>

            {/* Module status */}
            <section>
                <div className="mb-4">
                    <h2 className="text-xl font-bold text-primary m-0">Modules</h2>
                    <p className="text-secondary text-sm mt-1 mb-0">
                        Live status of every configured module.
                    </p>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {moduleList.map(mod => {
                        const state = runStates[mod.name];
                        const lastRun = mod.last_run || state?.last_run;
                        const lastStatus = mod.last_run_status || state?.status;
                        const schedule = mod.schedule;
                        const jobId = state?.job_id;
                        const isRunning = lastStatus === 'running';

                        return (
                            <div
                                key={mod.name}
                                className="bg-surface border border-border-light rounded-lg p-4 flex flex-col gap-2 min-w-0"
                            >
                                <div className="flex items-center justify-between gap-2 min-w-0">
                                    <span className="font-semibold text-primary truncate min-w-0">
                                        {humanize(mod.name)}
                                    </span>
                                    <div className="flex items-center gap-1 shrink-0">
                                        {lastStatus && (
                                            <span
                                                className={`text-xs px-2 py-1 rounded-full ${statusPillClass(lastStatus)}`}
                                            >
                                                {lastStatus}
                                            </span>
                                        )}
                                        {isRunning && jobId && (
                                            <IconButton
                                                icon="cancel"
                                                aria-label={`Cancel ${humanize(mod.name)}`}
                                                variant="ghost"
                                                onClick={() => handleCancel(mod.name, jobId)}
                                            />
                                        )}
                                    </div>
                                </div>
                                <div className="text-sm text-secondary break-words">
                                    {schedule ? (
                                        <span>Schedule: {scheduleToHuman(schedule)}</span>
                                    ) : (
                                        <span className="inline-flex items-center gap-2">
                                            <span className="text-xs px-2 py-0.5 rounded-full bg-surface-alt text-tertiary">
                                                Manual only
                                            </span>
                                            {!isRunning && (
                                                <button
                                                    type="button"
                                                    onClick={() => handleRunNow(mod.name)}
                                                    className="text-xs text-accent hover:underline bg-transparent border-0 p-0 cursor-pointer"
                                                >
                                                    Run now
                                                </button>
                                            )}
                                        </span>
                                    )}
                                </div>
                                {lastRun && (
                                    <div className="text-xs text-tertiary">
                                        Last run: {formatTimeAgo(lastRun, new Date(tick))}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </section>

            {/* Footer */}
            {version && (
                <footer className="text-xs text-tertiary text-center pt-4 border-t border-border-light">
                    CHUB {typeof version === 'string' ? version : ''}
                </footer>
            )}
        </div>
    );
};

export default DashboardPage;
