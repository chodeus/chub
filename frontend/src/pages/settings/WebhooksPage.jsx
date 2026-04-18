import React, { useMemo } from 'react';
import { useApiData, useApiMutation } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { webhooksAPI } from '../../utils/api/webhooks.js';
import { Card } from '../../components/ui/card/Card.jsx';
import { LoadingButton, IconButton, PageHeader } from '../../components/ui';
import Spinner from '../../components/ui/Spinner.jsx';

export const WebhooksPage = () => {
    const toast = useToast();

    const {
        data: unmatchedData,
        isLoading: unmatchedLoading,
        refresh: refreshUnmatched,
    } = useApiData({
        apiFunction: webhooksAPI.getUnmatchedStatus,
        options: { showErrorToast: false },
    });

    const {
        data: cleanurrData,
        isLoading: cleanurrLoading,
        refresh: refreshCleanarr,
    } = useApiData({
        apiFunction: webhooksAPI.getCleanarrStatus,
        options: { showErrorToast: false },
    });

    const { execute: processUnmatched, isLoading: isProcessingUnmatched } = useApiMutation(
        () => webhooksAPI.processUnmatched(),
        {
            successMessage: 'Unmatched assets processing initiated',
            onSuccess: () => refreshUnmatched(),
        }
    );

    const { execute: processCleanarr, isLoading: isProcessingCleanarr } = useApiMutation(
        () => webhooksAPI.processCleanarr(),
        {
            successMessage: 'Cleanarr processing initiated',
            onSuccess: () => refreshCleanarr(),
        }
    );

    const unmatchedStatus = useMemo(() => unmatchedData?.data || {}, [unmatchedData]);
    const cleanurrStatus = useMemo(() => cleanurrData?.data || {}, [cleanurrData]);

    const handleRefreshAll = () => {
        refreshUnmatched();
        refreshCleanarr();
        toast.success('Webhook status refreshed');
    };

    const handleProcessUnmatched = async () => {
        try {
            await processUnmatched();
        } catch {
            toast.error('Failed to process unmatched assets');
        }
    };

    const handleProcessCleanarr = async () => {
        try {
            await processCleanarr();
        } catch {
            toast.error('Failed to run cleanarr');
        }
    };

    if (unmatchedLoading && cleanurrLoading) {
        return <Spinner size="large" text="Loading webhook status..." center />;
    }

    return (
        <div className="flex flex-col gap-6">
            <PageHeader
                title="Webhooks"
                description="Inbound event sources and cleanup operations."
                badge={3}
                icon="webhook"
                actions={
                    <IconButton
                        icon="refresh"
                        aria-label="Refresh webhook status"
                        variant="ghost"
                        onClick={handleRefreshAll}
                    />
                }
            />

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Unmatched Assets */}
                <Card variant="bordered">
                    <Card.Body>
                        <div className="flex flex-col gap-4">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <span className="material-symbols-outlined text-warning">
                                        search_off
                                    </span>
                                    <h3 className="text-lg font-semibold text-primary">
                                        Unmatched Assets
                                    </h3>
                                </div>
                                <span
                                    className={`text-xs px-2 py-1 rounded-full font-medium ${
                                        unmatchedStatus.status === 'active'
                                            ? 'bg-success/15 text-success'
                                            : 'bg-secondary/15 text-secondary'
                                    }`}
                                >
                                    {unmatchedStatus.status || 'unknown'}
                                </span>
                            </div>

                            {unmatchedStatus.summary && (
                                <div className="grid grid-cols-2 gap-3">
                                    {Object.entries(unmatchedStatus.summary).map(([key, value]) => (
                                        <div key={key} className="p-2 rounded bg-surface-alt">
                                            <span className="text-xs text-secondary block capitalize">
                                                {key.replace(/_/g, ' ')}
                                            </span>
                                            <span className="font-medium text-primary">
                                                {typeof value === 'number'
                                                    ? value
                                                    : typeof value === 'object' && value !== null
                                                      ? (value.total ??
                                                        value.unmatched ??
                                                        JSON.stringify(value))
                                                      : String(value)}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            )}

                            <LoadingButton
                                loading={isProcessingUnmatched}
                                loadingText="Processing..."
                                variant="primary"
                                icon="play_arrow"
                                onClick={handleProcessUnmatched}
                            >
                                Process Unmatched
                            </LoadingButton>
                        </div>
                    </Card.Body>
                </Card>

                {/* Cleanarr */}
                <Card variant="bordered">
                    <Card.Body>
                        <div className="flex flex-col gap-4">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <span className="material-symbols-outlined text-brand-primary">
                                        cleaning_services
                                    </span>
                                    <h3 className="text-lg font-semibold text-primary">Cleanarr</h3>
                                </div>
                                <span
                                    className={`text-xs px-2 py-1 rounded-full font-medium ${
                                        cleanurrStatus.status === 'active'
                                            ? 'bg-success/15 text-success'
                                            : 'bg-secondary/15 text-secondary'
                                    }`}
                                >
                                    {cleanurrStatus.status || 'unknown'}
                                </span>
                            </div>

                            {cleanurrStatus.orphaned_count != null && (
                                <div className="p-3 rounded bg-surface-alt">
                                    <span className="text-xs text-secondary block">
                                        Orphaned Posters
                                    </span>
                                    <span className="text-2xl font-bold text-warning">
                                        {cleanurrStatus.orphaned_count}
                                    </span>
                                </div>
                            )}

                            {cleanurrStatus.summary && (
                                <div className="grid grid-cols-2 gap-3">
                                    {Object.entries(cleanurrStatus.summary).map(([key, value]) => (
                                        <div key={key} className="p-2 rounded bg-surface-alt">
                                            <span className="text-xs text-secondary block capitalize">
                                                {key.replace(/_/g, ' ')}
                                            </span>
                                            <span className="font-medium text-primary">
                                                {typeof value === 'number'
                                                    ? value
                                                    : typeof value === 'object' && value !== null
                                                      ? Object.entries(value)
                                                            .map(([k, v]) => `${k}: ${v}`)
                                                            .join(', ')
                                                      : String(value)}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            )}

                            <LoadingButton
                                loading={isProcessingCleanarr}
                                loadingText="Cleaning..."
                                variant="warning"
                                icon="cleaning_services"
                                onClick={handleProcessCleanarr}
                            >
                                Run Cleanup
                            </LoadingButton>
                        </div>
                    </Card.Body>
                </Card>
            </div>
        </div>
    );
};

export default WebhooksPage;
