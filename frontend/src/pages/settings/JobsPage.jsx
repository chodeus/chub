import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useApiData, useApiMutation } from '../../hooks/useApiData.js';
import { useModuleEvents } from '../../hooks/useModuleEvents.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { jobsAPI } from '../../utils/api/jobs.js';
import { modulesAPI } from '../../utils/api/modules.js';
import { StatGrid } from '../../components/statistics';
import { StatCard, LoadingButton, IconButton, PageHeader } from '../../components/ui';
import Spinner from '../../components/ui/Spinner.jsx';
import { formatDateTime } from '../../utils/datetime.js';
import { useUIState } from '../../contexts/UIStateContext.jsx';

const STATUS_FILTERS = ['all', 'pending', 'running', 'completed', 'error'];

const STATUS_COLORS = {
    pending: 'bg-warning/20 text-warning',
    running: 'bg-primary/20 text-primary',
    completed: 'bg-success/20 text-success',
    success: 'bg-success/20 text-success',
    error: 'bg-error/20 text-error',
    cancelled: 'bg-secondary/20 text-secondary',
};

// Icon + colour per phase status for the per-job phase timeline.
const PHASE_META = {
    success: { icon: 'check_circle', cls: 'text-success' },
    running: { icon: 'progress_activity', cls: 'text-primary animate-spin' },
    error: { icon: 'error', cls: 'text-error' },
    skipped: { icon: 'do_not_disturb_on', cls: 'text-secondary' },
    pending: { icon: 'schedule', cls: 'text-tertiary' },
};

export const JobsPage = () => {
    const toast = useToast();
    const { isMobile } = useUIState();
    const [activeFilter, setActiveFilter] = useState('all');
    const [expandedJobId, setExpandedJobId] = useState(null);
    const [jobDetail, setJobDetail] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);
    // Tracks the row whose detail is currently being loaded. Rapid toggling
    // can resolve out of order, so each async result checks this before
    // committing — otherwise a slow earlier fetch could render under a row the
    // user has since expanded to a different job.
    const detailReqRef = useRef(null);

    const handleToggleDetail = async (jobId, job) => {
        if (expandedJobId === jobId) {
            detailReqRef.current = null;
            setExpandedJobId(null);
            setJobDetail(null);
            return;
        }
        detailReqRef.current = jobId;
        setExpandedJobId(jobId);
        setDetailLoading(true);
        try {
            const result = await jobsAPI.getJob(jobId);
            const detail = result?.data?.job || result?.data || {};

            // For running module jobs, also fetch live execution status
            if (
                job?.status === 'running' &&
                (job?.job_type === 'module_run' || job?.type === 'module_run')
            ) {
                try {
                    const moduleName = detail.module || job.module;
                    if (moduleName) {
                        const execStatus = await modulesAPI.getExecutionStatus(moduleName, jobId);
                        detail._executionStatus = execStatus?.data || null;
                    }
                } catch {
                    // Execution status is optional — don't fail the whole detail
                }
            }

            // Only commit if this is still the row the user is expanding.
            if (detailReqRef.current === jobId) {
                setJobDetail(detail);
            }
        } catch {
            if (detailReqRef.current === jobId) {
                setJobDetail(null);
            }
        } finally {
            if (detailReqRef.current === jobId) {
                setDetailLoading(false);
            }
        }
    };

    // While a job is expanded and still running/pending, re-fetch its detail
    // every few seconds so the phase timeline advances live. Bypasses the
    // getJob cache for freshness; stops once the job reaches a terminal status.
    useEffect(() => {
        if (expandedJobId == null) return undefined;
        const status = jobDetail?.status;
        if (status && status !== 'running' && status !== 'pending') return undefined;
        const id = setInterval(async () => {
            try {
                const result = await jobsAPI.getJob(expandedJobId, { useCache: false });
                const detail = result?.data?.job || result?.data || {};
                if (detailReqRef.current === expandedJobId) {
                    setJobDetail(prev => ({
                        ...detail,
                        _executionStatus: prev?._executionStatus,
                    }));
                }
            } catch {
                /* transient fetch error — keep the last detail */
            }
        }, 3000);
        return () => clearInterval(id);
    }, [expandedJobId, jobDetail?.status]);

    const fetchJobsFiltered = useCallback(
        () =>
            jobsAPI.listJobs(
                activeFilter !== 'all' ? { status: activeFilter, limit: 100 } : { limit: 100 }
            ),
        [activeFilter]
    );

    const {
        data: statsData,
        isLoading: statsLoading,
        refresh: refreshStats,
    } = useApiData({
        apiFunction: jobsAPI.getStats,
        options: { showErrorToast: false },
    });

    const {
        data: jobsData,
        isLoading: jobsLoading,
        refresh: refreshJobs,
    } = useApiData({
        apiFunction: fetchJobsFiltered,
        options: { showErrorToast: false },
        dependencies: [activeFilter],
    });

    const { execute: retryJob, isLoading: isRetrying } = useApiMutation(
        jobId => jobsAPI.retryJob(jobId),
        { successMessage: 'Job queued for retry' }
    );

    // SSE real-time updates
    const handleStatusChange = useCallback(() => {
        refreshStats();
        refreshJobs();
    }, [refreshStats, refreshJobs]);

    useModuleEvents({ onStatusChange: handleStatusChange });

    // Module execution history
    const { data: historyData } = useApiData({
        apiFunction: () => modulesAPI.fetchExecutionHistory(null, { limit: 20 }),
        options: { showErrorToast: false },
    });

    const executionHistory = useMemo(
        () => historyData?.data?.history || historyData?.data || [],
        [historyData]
    );

    const handleRefresh = useCallback(() => {
        refreshStats();
        refreshJobs();
    }, [refreshStats, refreshJobs]);

    const handleRetry = async jobId => {
        try {
            await retryJob(jobId);
            refreshJobs();
            refreshStats();
        } catch {
            toast.error('Failed to retry job');
        }
    };

    const jobStats = useMemo(() => {
        const counts = statsData?.data?.status_counts || {};
        return {
            pending: counts.pending || 0,
            running: counts.running || 0,
            completed: counts.success || 0,
            failed: counts.error || 0,
        };
    }, [statsData]);

    const jobs = useMemo(() => jobsData?.data?.jobs || [], [jobsData]);

    // Tick every second so running-job durations update live. Keeps Date.now()
    // out of render (react-hooks/impure-function-during-render).
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        const id = setInterval(() => setNow(Date.now()), 1000);
        return () => clearInterval(id);
    }, []);

    const formatSeconds = seconds => {
        if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '-';
        const s = Math.round(seconds);
        if (s < 60) return `${s}s`;
        const minutes = Math.floor(s / 60);
        const secs = s % 60;
        return `${minutes}m ${secs}s`;
    };

    // Duration sources, in priority order:
    //   1. result.data.duration — present on module_run success rows that opt in
    //   2. completed_at - started_at — written by the worker on every terminal
    //      transition (success/error/cancelled), so error rows and any job type
    //      without a result payload still get a real number
    //   3. now - started_at — live timer while the job is running/pending
    //   4. '-' — rows from before the started_at/completed_at columns existed
    const jobDuration = job => {
        try {
            const parsed = job.result ? JSON.parse(job.result) : null;
            const d = parsed?.data?.duration;
            if (typeof d === 'number') return formatSeconds(d);
        } catch {
            /* malformed result; fall through */
        }
        if (job.completed_at) {
            const start = job.started_at || job.received_at;
            if (start) {
                const ms = new Date(job.completed_at).getTime() - new Date(start).getTime();
                return formatSeconds(ms / 1000);
            }
        }
        if (job.status === 'running' || job.status === 'pending') {
            const start = job.started_at || job.received_at;
            if (start) return formatSeconds((now - new Date(start).getTime()) / 1000);
        }
        return '-';
    };

    const formatTime = ts => {
        if (!ts) return '-';
        return formatDateTime(ts);
    };

    // Per-job phase timeline (poster_renamerr / asset_renamerr emit phases).
    // Running phases show a live-ticking elapsed time; finished phases show
    // their recorded duration; pending/skipped show none.
    const renderPhases = phases => {
        if (!Array.isArray(phases) || phases.length === 0) return null;
        return (
            <div className="col-span-full">
                <span className="text-tertiary capitalize block mb-1">Phases</span>
                <div className="flex flex-col gap-1">
                    {phases.map((p, i) => {
                        const meta = PHASE_META[p.status] || PHASE_META.pending;
                        let dur = '';
                        if (typeof p.duration_s === 'number') {
                            dur = formatSeconds(p.duration_s);
                        } else if (p.status === 'running' && p.started_at) {
                            dur = formatSeconds((now - new Date(p.started_at).getTime()) / 1000);
                        }
                        return (
                            <div
                                key={`${p.name}-${i}`}
                                className="flex items-center justify-between gap-2 px-2 py-1 rounded bg-surface-alt"
                            >
                                <span className="flex items-center gap-1.5 min-w-0">
                                    <span
                                        className={`material-symbols-outlined text-base leading-none ${meta.cls}`}
                                    >
                                        {meta.icon}
                                    </span>
                                    <span className="text-primary truncate">{p.name}</span>
                                </span>
                                <span className="text-secondary shrink-0 tabular-nums">{dur}</span>
                            </div>
                        );
                    })}
                </div>
            </div>
        );
    };

    if (statsLoading && jobsLoading) {
        return <Spinner size="large" text="Loading jobs..." center />;
    }

    return (
        <div className="flex flex-col gap-6">
            <PageHeader
                title="Jobs"
                description="Monitor queued and completed runs."
                badge={2}
                icon="work_history"
                actions={
                    <IconButton
                        icon="refresh"
                        aria-label="Refresh jobs"
                        variant="ghost"
                        onClick={handleRefresh}
                    />
                }
            />

            <StatGrid columns={4}>
                <StatCard
                    label="Pending"
                    value={jobStats.pending}
                    valueColor={jobStats.pending > 0 ? 'warning' : ''}
                />
                <StatCard
                    label="Running"
                    value={jobStats.running}
                    valueColor={jobStats.running > 0 ? 'primary' : ''}
                />
                <StatCard label="Completed" value={jobStats.completed} valueColor="success" />
                <StatCard
                    label="Failed"
                    value={jobStats.failed}
                    valueColor={jobStats.failed > 0 ? 'error' : ''}
                />
            </StatGrid>

            {/* Filter buttons */}
            <div className="flex flex-wrap items-center gap-2">
                {STATUS_FILTERS.map(filter => (
                    <button
                        key={filter}
                        type="button"
                        onClick={() => setActiveFilter(filter)}
                        className={`px-3 py-1.5 rounded-lg text-sm font-medium capitalize cursor-pointer border transition-colors ${
                            activeFilter === filter
                                ? 'bg-primary/15 text-primary border-primary/30'
                                : 'bg-transparent text-secondary border-border hover:text-primary'
                        }`}
                    >
                        {filter}
                    </button>
                ))}
            </div>

            {/* Job list */}
            {jobsLoading ? (
                <Spinner size="medium" text="Loading jobs..." center />
            ) : jobs.length === 0 ? (
                <div className="text-center py-12 text-secondary">
                    <span className="material-symbols-outlined text-4xl mb-2 block">inbox</span>
                    No jobs found{activeFilter !== 'all' ? ` with status "${activeFilter}"` : ''}
                </div>
            ) : isMobile ? (
                <div className="flex flex-col gap-2">
                    {jobs.map(job => {
                        const isOpen = expandedJobId === job.id;
                        const typeLabel = job.module_name || job.job_type || job.type || '-';
                        return (
                            <div
                                key={job.id}
                                className="border border-border rounded-lg bg-surface p-3 flex flex-col gap-2"
                            >
                                <div className="flex items-start justify-between gap-2">
                                    <span className="inline-block px-2 py-0.5 rounded bg-surface-alt text-primary text-xs font-medium break-words min-w-0">
                                        {typeLabel}
                                    </span>
                                    <span
                                        className={`shrink-0 px-2 py-0.5 rounded-full text-xs font-medium capitalize ${STATUS_COLORS[job.status] || 'bg-surface text-secondary'}`}
                                    >
                                        {job.status}
                                    </span>
                                </div>
                                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-secondary">
                                    <span>
                                        <span className="text-tertiary">#</span>
                                        {job.id}
                                    </span>
                                    <span>{formatTime(job.received_at || job.created_at)}</span>
                                    <span>{jobDuration(job)}</span>
                                </div>
                                <div className="flex items-center justify-end gap-1">
                                    <IconButton
                                        icon={isOpen ? 'expand_less' : 'expand_more'}
                                        aria-label="Toggle detail"
                                        variant="ghost"
                                        onClick={() => handleToggleDetail(job.id, job)}
                                    />
                                    {(job.status === 'error' || job.status === 'success') && (
                                        <LoadingButton
                                            loading={isRetrying}
                                            loadingText="..."
                                            variant="ghost"
                                            icon="replay"
                                            onClick={() => handleRetry(job.id)}
                                        >
                                            Retry
                                        </LoadingButton>
                                    )}
                                </div>
                                {isOpen && (
                                    <div className="border-t border-border pt-2">
                                        {detailLoading ? (
                                            <span className="text-xs text-secondary">
                                                Loading...
                                            </span>
                                        ) : jobDetail ? (
                                            <div className="grid grid-cols-2 gap-2 text-xs">
                                                {Object.entries(jobDetail)
                                                    .filter(
                                                        ([, v]) =>
                                                            v != null &&
                                                            v !== '' &&
                                                            typeof v !== 'object'
                                                    )
                                                    .map(([k, v]) => (
                                                        <div
                                                            key={k}
                                                            className="flex flex-col justify-center gap-1 px-3 py-2 rounded-lg bg-surface-alt"
                                                        >
                                                            <span className="text-tertiary capitalize block">
                                                                {k.replace(/_/g, ' ')}
                                                            </span>
                                                            <span className="text-primary break-words">
                                                                {String(v)}
                                                            </span>
                                                        </div>
                                                    ))}
                                                {renderPhases(jobDetail.phases)}
                                                {jobDetail.error && (
                                                    <div className="col-span-full p-2 rounded bg-error/10 text-error text-xs">
                                                        {jobDetail.error}
                                                    </div>
                                                )}
                                            </div>
                                        ) : (
                                            <span className="text-xs text-tertiary">
                                                No detail available
                                            </span>
                                        )}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            ) : (
                <div className="border border-border rounded-lg overflow-hidden">
                    <table className="w-full text-sm table-fixed sm:table-auto">
                        <thead>
                            <tr className="bg-surface-alt border-b border-border">
                                <th className="hidden sm:table-cell text-left px-4 py-3 font-medium text-secondary">
                                    ID
                                </th>
                                <th className="text-left px-2 sm:px-4 py-3 font-medium text-secondary">
                                    Type
                                </th>
                                <th className="text-left px-2 sm:px-4 py-3 font-medium text-secondary">
                                    Status
                                </th>
                                <th className="text-left px-2 sm:px-4 py-3 font-medium text-secondary">
                                    Created
                                </th>
                                <th className="hidden sm:table-cell text-left px-4 py-3 font-medium text-secondary">
                                    Duration
                                </th>
                                <th className="text-right px-2 sm:px-4 py-3 font-medium text-secondary">
                                    Actions
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {jobs.map(job => (
                                <React.Fragment key={job.id}>
                                    <tr className="border-b border-border last:border-b-0 hover:bg-surface-alt/50">
                                        <td className="hidden sm:table-cell px-4 py-3 font-mono text-xs text-tertiary">
                                            #{job.id}
                                        </td>
                                        <td className="px-2 sm:px-4 py-3">
                                            <span className="inline-block px-2 py-0.5 rounded bg-surface-alt text-primary text-xs font-medium break-all">
                                                {job.module_name || job.job_type || job.type || '-'}
                                            </span>
                                        </td>
                                        <td className="px-2 sm:px-4 py-3">
                                            <span
                                                className={`px-2 py-0.5 rounded-full text-xs font-medium capitalize ${STATUS_COLORS[job.status] || 'bg-surface text-secondary'}`}
                                            >
                                                {job.status}
                                            </span>
                                        </td>
                                        <td className="px-2 sm:px-4 py-3 text-secondary text-xs">
                                            {formatTime(job.received_at || job.created_at)}
                                        </td>
                                        <td className="hidden sm:table-cell px-4 py-3 text-secondary text-xs">
                                            {jobDuration(job)}
                                        </td>
                                        <td className="px-2 sm:px-4 py-3 text-right">
                                            <div className="flex items-center justify-end gap-1">
                                                <IconButton
                                                    icon={
                                                        expandedJobId === job.id
                                                            ? 'expand_less'
                                                            : 'expand_more'
                                                    }
                                                    aria-label="Toggle detail"
                                                    variant="ghost"
                                                    onClick={() => handleToggleDetail(job.id, job)}
                                                />
                                                {(job.status === 'error' ||
                                                    job.status === 'success') && (
                                                    <LoadingButton
                                                        loading={isRetrying}
                                                        loadingText="..."
                                                        variant="ghost"
                                                        icon="replay"
                                                        onClick={() => handleRetry(job.id)}
                                                    >
                                                        Retry
                                                    </LoadingButton>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                    {expandedJobId === job.id && (
                                        <tr className="bg-surface-alt/30">
                                            <td colSpan={6} className="px-4 py-3">
                                                {detailLoading ? (
                                                    <span className="text-xs text-secondary">
                                                        Loading...
                                                    </span>
                                                ) : jobDetail ? (
                                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                                                        {Object.entries(jobDetail)
                                                            .filter(
                                                                ([, v]) =>
                                                                    v != null &&
                                                                    v !== '' &&
                                                                    typeof v !== 'object'
                                                            )
                                                            .map(([k, v]) => (
                                                                <div
                                                                    key={k}
                                                                    className="flex flex-col justify-center gap-1 px-3 py-2 rounded-lg bg-surface-alt"
                                                                >
                                                                    <span className="text-tertiary capitalize block">
                                                                        {k.replace(/_/g, ' ')}
                                                                    </span>
                                                                    <span className="text-primary break-words">
                                                                        {String(v)}
                                                                    </span>
                                                                </div>
                                                            ))}
                                                        {renderPhases(jobDetail.phases)}
                                                        {jobDetail.error && (
                                                            <div className="col-span-full p-2 rounded bg-error/10 text-error text-xs">
                                                                {jobDetail.error}
                                                            </div>
                                                        )}
                                                    </div>
                                                ) : (
                                                    <span className="text-xs text-tertiary">
                                                        No detail available
                                                    </span>
                                                )}
                                            </td>
                                        </tr>
                                    )}
                                </React.Fragment>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Module Execution History */}
            {Array.isArray(executionHistory) && executionHistory.length > 0 && (
                <section>
                    <h3 className="text-lg font-semibold text-primary mb-3">
                        Recent Module Executions
                    </h3>
                    <div className="space-y-1">
                        {executionHistory.map((entry, i) => (
                            <div
                                key={entry.id || i}
                                className="flex items-center justify-between p-2 rounded bg-surface border border-border text-sm"
                            >
                                <div className="flex items-center gap-3">
                                    <span
                                        className={`w-2 h-2 rounded-full ${
                                            entry.status === 'success'
                                                ? 'bg-success'
                                                : entry.status === 'error'
                                                  ? 'bg-error'
                                                  : 'bg-secondary'
                                        }`}
                                    />
                                    <span className="text-primary font-medium">
                                        {entry.module_name ||
                                            entry.module ||
                                            entry.name ||
                                            entry.type ||
                                            '-'}
                                    </span>
                                </div>
                                <div className="flex items-center gap-3 text-xs text-secondary">
                                    <span className="capitalize">{entry.status}</span>
                                    {entry.duration != null && <span>{entry.duration}s</span>}
                                    {entry.completed_at && (
                                        <span>{formatDateTime(entry.completed_at)}</span>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </section>
            )}
        </div>
    );
};

export default JobsPage;
