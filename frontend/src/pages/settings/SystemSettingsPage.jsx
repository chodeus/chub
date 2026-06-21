import React, { useState, useCallback } from 'react';
import { useApiData } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { systemAPI } from '../../utils/api/system.js';
import { Button, Card, IconButton, LoadingButton, PageHeader, StatCard } from '../../components/ui';
import { Modal } from '../../components/modals/Modal';
import Spinner from '../../components/ui/Spinner.jsx';
import { StatGrid } from '../../components/statistics';
import { formatDateTime as fmtDateTime } from '../../utils/datetime.js';
import { useUIState } from '../../contexts/UIStateContext.jsx';

const formatBytes = bytes => {
    if (!bytes) return '0 B';
    const u = ['B', 'KB', 'MB', 'GB', 'TB'];
    let n = bytes;
    let i = 0;
    while (n >= 1024 && i < u.length - 1) {
        n /= 1024;
        i += 1;
    }
    return `${n.toFixed(1)} ${u[i]}`;
};

const formatNumber = n => (n == null ? '-' : n.toLocaleString());

const formatDateTime = ts => (ts ? fmtDateTime(ts) : '-');

export const SystemSettingsPage = () => {
    const toast = useToast();
    const { isMobile } = useUIState();
    const [confirmClearPoster, setConfirmClearPoster] = useState(false);
    const [vacuuming, setVacuuming] = useState(false);
    const [clearing, setClearing] = useState(false);

    const {
        data: statsData,
        isLoading,
        refresh: refreshStats,
    } = useApiData({
        apiFunction: systemAPI.getDbStats,
        options: { showErrorToast: false },
    });

    const stats = statsData?.data || {};
    const tables = stats.tables || [];
    const migrations = stats.schema_migrations || [];
    const totalRows = tables.reduce((sum, t) => sum + (t.rows || 0), 0);

    const handleVacuum = useCallback(async () => {
        setVacuuming(true);
        try {
            const result = await systemAPI.vacuumDb();
            const reclaimed = result?.data?.bytes_reclaimed ?? 0;
            const duration = result?.data?.duration_ms ?? 0;
            toast.success(
                reclaimed > 0
                    ? `Compacted in ${duration}ms — reclaimed ${formatBytes(reclaimed)}`
                    : `Compacted in ${duration}ms — nothing to reclaim`
            );
            refreshStats();
        } catch (e) {
            toast.error(`VACUUM failed: ${e?.message || 'unknown error'}`);
        } finally {
            setVacuuming(false);
        }
    }, [toast, refreshStats]);

    const handleClearPosterCache = useCallback(async () => {
        setClearing(true);
        try {
            const result = await systemAPI.clearPosterCache();
            const deleted = result?.data?.deleted ?? 0;
            toast.success(
                `Deleted ${formatNumber(deleted)} poster_cache rows. Run poster_renamerr to repopulate.`
            );
            setConfirmClearPoster(false);
            refreshStats();
        } catch (e) {
            toast.error(`Clear failed: ${e?.message || 'unknown error'}`);
        } finally {
            setClearing(false);
        }
    }, [toast, refreshStats]);

    if (isLoading && !statsData) {
        return <Spinner size="large" text="Loading database stats..." center />;
    }

    return (
        <div className="flex flex-col gap-6">
            <PageHeader
                title="System"
                description="Database statistics and maintenance actions."
                icon="database"
                actions={
                    <IconButton
                        icon="refresh"
                        aria-label="Refresh stats"
                        variant="ghost"
                        onClick={refreshStats}
                    />
                }
            />

            <StatGrid columns={4}>
                <StatCard label="Total Rows" value={formatNumber(totalRows)} icon="table_rows" />
                <StatCard
                    label="Database File"
                    value={formatBytes(stats.file_bytes)}
                    icon="storage"
                />
                <StatCard
                    label="Reclaimable"
                    value={formatBytes(stats.free_bytes)}
                    valueColor={stats.free_bytes > 1024 * 1024 ? 'warning' : ''}
                    icon="recycling"
                />
                <StatCard
                    label="Schema Migrations"
                    value={formatNumber(migrations.length)}
                    icon="history_edu"
                />
            </StatGrid>

            <Card variant="bordered">
                <Card.Header title="Database Statistics" />
                <Card.Body>
                    {isMobile ? (
                        <div className="flex flex-col gap-1.5">
                            {tables.map(t => (
                                <div
                                    key={t.name}
                                    className="flex items-center justify-between gap-3 px-3 py-2 rounded bg-surface border border-border"
                                >
                                    <span className="text-fg font-mono text-xs break-all min-w-0">
                                        {t.name}
                                    </span>
                                    <span className="shrink-0 text-fg-muted text-sm">
                                        {formatNumber(t.rows)}
                                    </span>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="overflow-x-auto rounded-lg border border-border">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="bg-surface-alt text-fg-muted text-left">
                                        <th className="px-3 py-2 font-medium">Table</th>
                                        <th className="px-3 py-2 font-medium text-right">Rows</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-border">
                                    {tables.map(t => (
                                        <tr
                                            key={t.name}
                                            className="bg-surface hover:bg-surface-alt"
                                        >
                                            <td className="px-3 py-2 text-fg font-mono text-xs">
                                                {t.name}
                                            </td>
                                            <td className="px-3 py-2 text-right text-fg-muted">
                                                {formatNumber(t.rows)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </Card.Body>
            </Card>

            <Card variant="bordered">
                <Card.Header title="Schema Migrations" />
                <Card.Body>
                    {migrations.length === 0 ? (
                        <p className="text-sm text-fg-subtle">No data migrations applied yet.</p>
                    ) : isMobile ? (
                        <div className="flex flex-col gap-2">
                            {migrations.map(m => (
                                <div
                                    key={m.name}
                                    className="flex flex-col gap-1 px-3 py-2 rounded bg-surface border border-border"
                                >
                                    <span className="text-fg font-mono text-xs break-all">
                                        {m.name}
                                    </span>
                                    <span className="text-fg-muted text-xs">
                                        Applied {formatDateTime(m.applied_at)}
                                    </span>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="overflow-x-auto rounded-lg border border-border">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="bg-surface-alt text-fg-muted text-left">
                                        <th className="px-3 py-2 font-medium">Name</th>
                                        <th className="px-3 py-2 font-medium">Applied</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-border">
                                    {migrations.map(m => (
                                        <tr
                                            key={m.name}
                                            className="bg-surface hover:bg-surface-alt"
                                        >
                                            <td className="px-3 py-2 text-fg font-mono text-xs">
                                                {m.name}
                                            </td>
                                            <td className="px-3 py-2 text-fg-muted">
                                                {formatDateTime(m.applied_at)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </Card.Body>
            </Card>

            <Card variant="bordered">
                <Card.Header title="Maintenance Actions" />
                <Card.Body>
                    <div className="flex flex-col gap-4">
                        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                            <div>
                                <p className="text-fg font-medium">Compact Database (VACUUM)</p>
                                <p className="text-sm text-fg-muted">
                                    Reclaims {formatBytes(stats.free_bytes)} of free pages. Safe to
                                    run any time but holds a brief write lock.
                                </p>
                            </div>
                            <LoadingButton
                                loading={vacuuming}
                                loadingText="Compacting..."
                                variant="primary"
                                icon="compress"
                                onClick={handleVacuum}
                            >
                                Compact Database
                            </LoadingButton>
                        </div>

                        <div className="border-t border-border" />

                        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                            <div>
                                <p className="text-fg font-medium">Rebuild Poster Cache</p>
                                <p className="text-sm text-fg-muted">
                                    Wipes the <code className="text-xs">poster_cache</code> table.
                                    The next <code className="text-xs">poster_renamerr</code> run
                                    does a fresh scan and repopulates it. Use after a code change
                                    has affected how posters are parsed or matched.
                                </p>
                            </div>
                            <Button
                                variant="danger"
                                icon="delete_sweep"
                                onClick={() => setConfirmClearPoster(true)}
                            >
                                Rebuild Poster Cache
                            </Button>
                        </div>
                    </div>
                </Card.Body>
            </Card>

            <Modal
                isOpen={confirmClearPoster}
                onClose={() => setConfirmClearPoster(false)}
                size="small"
            >
                <Modal.Header>Rebuild Poster Cache?</Modal.Header>
                <Modal.Body>
                    <p className="text-fg-muted">
                        This deletes every row in <code>poster_cache</code> (currently{' '}
                        <span className="font-semibold text-fg">
                            {formatNumber(tables.find(t => t.name === 'poster_cache')?.rows ?? 0)}
                        </span>{' '}
                        rows). The data itself isn&apos;t lost — your poster files on disk are
                        untouched. Run <code>poster_renamerr</code> afterwards to rescan and
                        repopulate.
                    </p>
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="ghost" onClick={() => setConfirmClearPoster(false)}>
                        Cancel
                    </Button>
                    <LoadingButton
                        loading={clearing}
                        loadingText="Clearing..."
                        variant="danger"
                        icon="delete_sweep"
                        onClick={handleClearPosterCache}
                    >
                        Rebuild
                    </LoadingButton>
                </Modal.Footer>
            </Modal>
        </div>
    );
};

export default SystemSettingsPage;
