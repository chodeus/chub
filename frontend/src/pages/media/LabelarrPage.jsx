import React, { useMemo } from 'react';
import { useApiData, useApiMutation } from '../../hooks/useApiData.js';
import { labelarrAPI } from '../../utils/api/labelarr.js';
import { modulesAPI } from '../../utils/api/modules.js';
import { LoadingButton, PageHeader } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';

const LabelarrPage = () => {
    const {
        data: statusData,
        isLoading,
        refresh: refreshStatus,
    } = useApiData({
        apiFunction: modulesAPI.fetchRunStates,
        options: { showErrorToast: false },
    });

    const { execute: runSync, isLoading: isSyncing } = useApiMutation(() => labelarrAPI.sync(), {
        successMessage: 'Label sync initiated',
        onSuccess: () => refreshStatus(),
    });

    const labelarrState = useMemo(() => {
        const states = statusData?.data || {};
        return states.labelarr || null;
    }, [statusData]);

    if (isLoading) return <Spinner size="large" text="Loading labelarr status..." center />;

    return (
        <div className="flex flex-col gap-6">
            <PageHeader
                title="Label Sync"
                description="Sync labels between Radarr/Sonarr and Plex."
                badge={5}
                icon="label"
                actions={
                    <LoadingButton
                        variant="primary"
                        icon="sync"
                        onClick={() => runSync()}
                        isLoading={isSyncing}
                    >
                        Sync Now
                    </LoadingButton>
                }
            />

            <section className="p-4 rounded-lg bg-surface border border-border">
                <h3 className="text-lg font-semibold text-primary mb-3 flex items-center gap-2">
                    <span className="material-symbols-outlined text-secondary">info</span>
                    About Label Sync
                </h3>
                <p className="text-secondary text-sm">
                    The labelarr module synchronizes tags between your Radarr/Sonarr instances and
                    Plex labels. This ensures your media is consistently tagged across all services
                    for filtering and organization.
                </p>
            </section>

            <section className="p-4 rounded-lg bg-surface border border-border">
                <h3 className="text-lg font-semibold text-primary mb-3 flex items-center gap-2">
                    <span className="material-symbols-outlined text-brand-primary">label</span>
                    Sync Status
                </h3>

                {labelarrState ? (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div className="p-3 rounded bg-surface-alt">
                            <span className="text-xs text-secondary block mb-1">Status</span>
                            <span
                                className={`font-medium capitalize ${
                                    labelarrState.status === 'success'
                                        ? 'text-success'
                                        : labelarrState.status === 'error'
                                          ? 'text-danger'
                                          : labelarrState.status === 'running'
                                            ? 'text-brand-primary'
                                            : 'text-primary'
                                }`}
                            >
                                {labelarrState.status || 'unknown'}
                            </span>
                        </div>
                        <div className="p-3 rounded bg-surface-alt">
                            <span className="text-xs text-secondary block mb-1">Last Run</span>
                            <span className="font-medium text-primary">
                                {labelarrState.last_run
                                    ? new Date(labelarrState.last_run).toLocaleString()
                                    : 'Never'}
                            </span>
                        </div>
                        {labelarrState.duration != null && (
                            <div className="p-3 rounded bg-surface-alt">
                                <span className="text-xs text-secondary block mb-1">Duration</span>
                                <span className="font-medium text-primary">
                                    {labelarrState.duration}s
                                </span>
                            </div>
                        )}
                        {labelarrState.message && (
                            <div className="p-3 rounded bg-surface-alt sm:col-span-2">
                                <span className="text-xs text-secondary block mb-1">Message</span>
                                <span className="text-sm text-primary">
                                    {labelarrState.message}
                                </span>
                            </div>
                        )}
                    </div>
                ) : (
                    <p className="text-secondary text-sm">
                        No sync history yet. Click &ldquo;Sync Now&rdquo; to run the first label
                        sync.
                    </p>
                )}
            </section>
        </div>
    );
};

export default LabelarrPage;
