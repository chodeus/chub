import React, { useMemo, useEffect, useRef, useCallback } from 'react';
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

const POLL_INTERVAL = 30000;

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
];

const listRecentJobs = (options = {}) => jobsAPI.listJobs({ status: 'success', limit: 4 }, options);

const DashboardPage = () => {
    const toast = useToast();
    const { user } = useAuth();

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

    const recentJobs = useMemo(() => {
        const jobs = recentJobsData?.data?.jobs || recentJobsData?.data || [];
        return Array.isArray(jobs) ? jobs.slice(0, 4) : [];
    }, [recentJobsData]);

    if (isLoading && moduleList.length === 0) {
        return <Spinner size="large" text="Loading dashboard..." center />;
    }

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

            {/* Quick start */}
            <section>
                <div className="mb-4">
                    <h2 className="text-xl font-bold text-primary m-0">Quick start</h2>
                    <p className="text-secondary text-sm mt-1 mb-0">
                        Jump straight into the things you do most.
                    </p>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
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

            {/* Recent jobs + Scheduler callout */}
            <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2">
                    <div className="flex items-end justify-between mb-4">
                        <div>
                            <h2 className="text-xl font-bold text-primary m-0">Recent jobs</h2>
                            <p className="text-secondary text-sm mt-1 mb-0">
                                The last four successful module runs.
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
                            No completed jobs yet. They&apos;ll show up here once modules start
                            running.
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            {recentJobs.map(job => {
                                const moduleName = job.module || job.job_type || 'job';
                                const ended = job.completed_at || job.updated_at || job.created_at;
                                return (
                                    <div
                                        key={job.id || `${moduleName}-${ended}`}
                                        className="bg-surface border border-border-light rounded-lg p-4 flex items-start gap-3"
                                    >
                                        <span
                                            className="badge-bubble badge-bubble--2 w-10 h-10 rounded-full flex items-center justify-center shrink-0"
                                            aria-hidden="true"
                                        >
                                            <span className="material-symbols-outlined text-base">
                                                check_circle
                                            </span>
                                        </span>
                                        <div className="min-w-0 flex-1">
                                            <div className="font-semibold text-primary truncate">
                                                {humanize(moduleName)}
                                            </div>
                                            <div className="text-xs text-tertiary mt-1">
                                                {ended
                                                    ? new Date(ended).toLocaleString()
                                                    : 'Completed'}
                                            </div>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>

                {/* Scheduler / status callout */}
                <div className="bg-surface-alt border border-border-light rounded-lg p-6 flex flex-col gap-4">
                    <div className="flex items-center gap-3">
                        <span
                            className="badge-bubble badge-bubble--3 w-11 h-11 rounded-full flex items-center justify-center"
                            aria-hidden="true"
                        >
                            <span className="material-symbols-outlined">schedule</span>
                        </span>
                        <div>
                            <div className="text-xs font-semibold uppercase tracking-wider text-tertiary">
                                Scheduler
                            </div>
                            <div className="text-lg font-bold text-primary">
                                {runningCount > 0
                                    ? `${runningCount} running`
                                    : scheduledCount > 0
                                      ? 'Active'
                                      : 'Idle'}
                            </div>
                        </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3 text-sm">
                        <div className="bg-surface rounded-lg px-3 py-2">
                            <div className="text-tertiary text-xs">Modules</div>
                            <div className="font-semibold text-primary">{moduleCount}</div>
                        </div>
                        <div className="bg-surface rounded-lg px-3 py-2">
                            <div className="text-tertiary text-xs">Scheduled</div>
                            <div className="font-semibold text-primary">{scheduledCount}</div>
                        </div>
                        <div className="bg-surface rounded-lg px-3 py-2">
                            <div className="text-tertiary text-xs">Pending</div>
                            <div className="font-semibold text-primary">{jobStats.pending}</div>
                        </div>
                        <div className="bg-surface rounded-lg px-3 py-2">
                            <div className="text-tertiary text-xs">Failed</div>
                            <div className="font-semibold text-error">{jobStats.failed}</div>
                        </div>
                    </div>
                    {version && (
                        <div className="text-xs text-tertiary mt-auto pt-2 border-t border-border-light">
                            CHUB {typeof version === 'string' ? version : ''}
                        </div>
                    )}
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

                        const statusClass =
                            lastStatus === 'success'
                                ? 'bg-success/20 text-success'
                                : lastStatus === 'error'
                                  ? 'bg-error/20 text-error'
                                  : lastStatus === 'running'
                                    ? 'bg-primary/20 text-primary'
                                    : 'bg-surface-alt text-secondary';

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
                                                className={`text-xs px-2 py-1 rounded-full ${statusClass}`}
                                            >
                                                {lastStatus}
                                            </span>
                                        )}
                                        {lastStatus === 'running' && jobId && (
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
                                        <span>Schedule: {schedule}</span>
                                    ) : (
                                        <span className="text-tertiary italic">Not scheduled</span>
                                    )}
                                </div>
                                {lastRun && (
                                    <div className="text-xs text-tertiary">
                                        Last run: {new Date(lastRun).toLocaleString()}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </section>
        </div>
    );
};

export default DashboardPage;
