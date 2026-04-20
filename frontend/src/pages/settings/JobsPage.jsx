import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useApiData, useApiMutation } from '../../hooks/useApiData.js';
import { useModuleEvents } from '../../hooks/useModuleEvents.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { jobsAPI } from '../../utils/api/jobs.js';
import { modulesAPI } from '../../utils/api/modules.js';
import { StatGrid } from '../../components/statistics';
import { StatCard, LoadingButton, IconButton, PageHeader } from '../../components/ui';
import Spinner from '../../components/ui/Spinner.jsx';

const STATUS_FILTERS = ['all', 'pending', 'running', 'completed', 'error'];

const STATUS_COLORS = {
    pending: 'bg-warning/20 text-warning',
    running: 'bg-primary/20 text-primary',
    completed: 'bg-success/20 text-success',
    success: 'bg-success/20 text-success',
    error: 'bg-error/20 text-error',
    cancelled: 'bg-secondary/20 text-secondary',
};

export const JobsPage = () => {
    const toast = useToast();
    const [activeFilter, setActiveFilter] = useState('all');
    const [expandedJobId, setExpandedJobId] = useState(null);
    const [jobDetail, setJobDetail] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);

    const handleToggleDetail = async (jobId, job) => {
        if (expandedJobId === jobId) {
            setExpandedJobId(null);
            setJobDetail(null);
            return;
        }
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

            setJobDetail(detail);
        } catch {
            setJobDetail(null);
        } finally {
            setDetailLoading(false);
        }
    };

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

    // Backend reports the real duration in `result.data.duration` (seconds).
    // For running/pending jobs fall back to "time since received" so the column
    // stays meaningful, but skip completed rows that lack the result payload.
    const jobDuration = job => {
        try {
            const parsed = job.result ? JSON.parse(job.result) : null;
            const d = parsed?.data?.duration;
            if (typeof d === 'number') return formatSeconds(d);
        } catch {
            /* malformed result; fall through */
        }
        if (job.status === 'running' || job.status === 'pending') {
            const start = job.started_at || job.received_at;
            if (start) return formatSeconds((now - new Date(start).getTime()) / 1000);
        }
        return '-';
    };

    const formatTime = ts => {
        if (!ts) return '-';
        return new Date(ts).toLocaleString();
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
                                                                    className="p-1.5 rounded bg-surface-alt"
                                                                >
                                                                    <span className="text-tertiary capitalize block">
                                                                        {k.replace(/_/g, ' ')}
                                                                    </span>
                                                                    <span className="text-primary break-words">
                                                                        {String(v)}
                                                                    </span>
                                                                </div>
                                                            ))}
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
                                        <span>{new Date(entry.completed_at).toLocaleString()}</span>
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
