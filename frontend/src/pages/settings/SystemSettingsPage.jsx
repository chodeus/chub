import React, { useState, useCallback, useRef } from 'react';
import { useApiData } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { systemAPI } from '../../utils/api/system.js';
import { configAPI } from '../../utils/api/config.js';
import { Button, LoadingButton } from '../../components/ui';
import Toggle from '../../components/ui/Toggle.jsx';
import { Modal } from '../../components/modals/Modal';
import Spinner from '../../components/ui/Spinner.jsx';
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

/** Relative "Xh ago" for the last-backup hint. */
const timeAgo = iso => {
    if (!iso) return null;
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return null;
    const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
    if (secs < 60) return 'just now';
    const mins = Math.round(secs / 60);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.round(hrs / 24)}d ago`;
};

/** A dense dark-inset section card matching the mock. */
const Section = ({ title, titleColor = 'text-fg', children, tone }) => (
    <section
        className={`rounded-xl p-5 ${
            tone === 'danger'
                ? 'bg-error/5 border border-error/25'
                : 'bg-surface border border-border'
        }`}
        style={tone === 'danger' ? undefined : { boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
    >
        <h2 className={`font-display text-[15px] font-semibold mb-4 ${titleColor}`}>{title}</h2>
        {children}
    </section>
);

/** Label + description on the left of a settings row. */
const RowLabel = ({ label, hint, mono }) => (
    <div className="min-w-0">
        <div className="text-sm font-medium text-fg">{label}</div>
        {hint != null && (
            <div className={`text-xs text-fg-subtle mt-0.5 ${mono ? 'font-mono' : ''}`}>{hint}</div>
        )}
    </div>
);

const Divider = () => <div className="h-px bg-border-light my-1" />;

/** Native select styled as the mock's inset pill. */
const InsetSelect = ({ value, onChange, disabled, children, ariaLabel }) => (
    <div className="relative shrink-0">
        <select
            value={value}
            onChange={onChange}
            disabled={disabled}
            aria-label={ariaLabel}
            className="appearance-none h-[34px] pl-3 pr-8 rounded-lg bg-surface-inset border border-border font-mono text-[13px] text-fg cursor-pointer disabled:opacity-50 focus:border-primary outline-none"
        >
            {children}
        </select>
        <span
            className="material-symbols-outlined text-fg-subtle text-[16px] absolute right-1.5 top-1/2 -translate-y-1/2 pointer-events-none"
            aria-hidden="true"
        >
            expand_more
        </span>
    </div>
);

const InsetInput = ({ value, onChange, onBlur, placeholder, ariaLabel }) => (
    <input
        type="text"
        value={value}
        onChange={onChange}
        onBlur={onBlur}
        placeholder={placeholder}
        aria-label={ariaLabel}
        className="h-[34px] w-[280px] max-w-full shrink-0 px-3 rounded-lg bg-surface-inset border border-border font-mono text-[13px] text-fg focus:border-primary outline-none"
    />
);

const LOG_LEVELS = ['debug', 'info', 'warning', 'error', 'critical'];
const RETENTION_OPTIONS = [
    { value: 0, label: 'Off' },
    { value: 7, label: '7 days' },
    { value: 14, label: '14 days' },
    { value: 30, label: '30 days' },
    { value: 60, label: '60 days' },
    { value: 90, label: '90 days' },
];

export const SystemSettingsPage = () => {
    const toast = useToast();
    const { isMobile } = useUIState();
    const restoreInputRef = useRef(null);

    const [confirmClearPoster, setConfirmClearPoster] = useState(false);
    const [vacuuming, setVacuuming] = useState(false);
    const [clearing, setClearing] = useState(false);
    const [backingUp, setBackingUp] = useState(false);
    const [restoring, setRestoring] = useState(false);
    const [showDbDetails, setShowDbDetails] = useState(false);

    // Version + on-demand update check.
    const { data: versionData } = useApiData({
        apiFunction: systemAPI.getVersion,
        options: { showErrorToast: false },
    });
    const version = versionData?.data?.version || '—';
    const [updateState, setUpdateState] = useState(null); // null | {checking} | result
    const [checkingUpdate, setCheckingUpdate] = useState(false);

    const checkUpdate = useCallback(async () => {
        setCheckingUpdate(true);
        try {
            const res = await systemAPI.checkForUpdate();
            setUpdateState(res?.data || null);
        } catch {
            toast.error('Update check failed');
        } finally {
            setCheckingUpdate(false);
        }
    }, [toast]);

    // General config (log level / retention / auto-backup) — immediate per-field save.
    const {
        data: generalData,
        refresh: refreshGeneral,
        isLoading: generalLoading,
    } = useApiData({
        apiFunction: useCallback(() => configAPI.fetchSection('general'), []),
        options: { showErrorToast: false },
    });
    const general = generalData?.data?.general || {};
    const [pending, setPending] = useState({}); // optimistic overrides while a save is in flight
    const cfg = key => (key in pending ? pending[key] : general[key]);

    // Free-text path, saved on blur rather than per keystroke. Re-seeded from
    // the server value when it changes — the render-time adjust pattern, not a
    // setState-in-effect.
    const serverBackupDir = general.backup_dir || '';
    const [backupDir, setBackupDir] = useState(serverBackupDir);
    const [lastServerBackupDir, setLastServerBackupDir] = useState(serverBackupDir);
    if (lastServerBackupDir !== serverBackupDir) {
        setLastServerBackupDir(serverBackupDir);
        setBackupDir(serverBackupDir);
    }

    const saveGeneral = useCallback(
        async (key, value) => {
            setPending(p => ({ ...p, [key]: value }));
            try {
                await configAPI.updateConfig({ general: { [key]: value } });
                refreshGeneral();
            } catch {
                toast.error('Failed to save setting');
                setPending(p => {
                    const next = { ...p };
                    delete next[key];
                    return next;
                });
            }
        },
        [refreshGeneral, toast]
    );

    // DB stats + backups list.
    const {
        data: statsData,
        isLoading: statsLoading,
        refresh: refreshStats,
    } = useApiData({ apiFunction: systemAPI.getDbStats, options: { showErrorToast: false } });
    const stats = statsData?.data || {};
    const tables = stats.tables || [];
    const migrations = stats.schema_migrations || [];
    const totalRows = tables.reduce((sum, t) => sum + (t.rows || 0), 0);

    const { data: backupsData, refresh: refreshBackups } = useApiData({
        apiFunction: systemAPI.listBackups,
        options: { showErrorToast: false },
    });
    const backups = backupsData?.data?.backups || [];
    const lastBackup = backups[0];

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

    const handleBackup = useCallback(async () => {
        setBackingUp(true);
        try {
            await systemAPI.downloadBackup();
            toast.success('Backup created and downloaded');
            refreshBackups();
        } catch (e) {
            toast.error(`Backup failed: ${e?.message || 'unknown error'}`);
        } finally {
            setBackingUp(false);
        }
    }, [toast, refreshBackups]);

    const handleRestoreFile = useCallback(
        async e => {
            const file = e.target.files?.[0];
            e.target.value = '';
            if (!file) return;
            setRestoring(true);
            try {
                await systemAPI.restoreBackup(file);
                toast.success('Config restored — restart to apply a database restore');
                refreshGeneral();
            } catch (err) {
                toast.error(`Restore failed: ${err?.message || 'invalid backup'}`);
            } finally {
                setRestoring(false);
            }
        },
        [toast, refreshGeneral]
    );

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

    if (statsLoading && !statsData && generalLoading && !generalData) {
        return <Spinner size="large" text="Loading system settings..." center />;
    }

    const dbFileBytes = stats.file_bytes;
    const posterRows = tables.find(t => t.name === 'poster_cache')?.rows ?? 0;

    return (
        <div className="flex flex-col gap-5">
            <div className="min-w-0">
                <h1 className="font-display text-[26px] font-bold tracking-[-0.3px] text-fg m-0">
                    System
                </h1>
                <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">
                    Logging, backups, database, and updates.
                </p>
            </div>

            <div className="flex flex-col gap-4 w-full max-w-[760px]">
                {/* VERSION */}
                <Section title="Version">
                    <div className="flex items-center gap-3 flex-wrap">
                        <span className="font-mono text-sm text-fg">{version}</span>
                        {updateState &&
                            (updateState.update_available ? (
                                <span className="font-mono text-[11px] px-2.5 py-[3px] rounded-full bg-warning/15 text-warning">
                                    update available{' '}
                                    {updateState.remote_version
                                        ? `· ${updateState.remote_version}`
                                        : ''}
                                </span>
                            ) : updateState.checked ? (
                                <span className="font-mono text-[11px] px-2.5 py-[3px] rounded-full bg-success/15 text-success">
                                    up to date
                                </span>
                            ) : (
                                <span className="font-mono text-[11px] px-2.5 py-[3px] rounded-full bg-surface-inset text-fg-subtle">
                                    check failed
                                </span>
                            ))}
                        <button
                            type="button"
                            onClick={checkUpdate}
                            disabled={checkingUpdate}
                            className="ml-auto text-[12.5px] text-accent hover:underline disabled:opacity-50"
                        >
                            {checkingUpdate ? 'Checking…' : 'Check for updates'}
                        </button>
                    </div>
                </Section>

                {/* LOGGING */}
                <Section title="Logging">
                    <div className="flex flex-wrap items-center justify-between gap-4 py-2">
                        <RowLabel label="Log level" hint="Verbosity written to module logs" />
                        <InsetSelect
                            ariaLabel="Log level"
                            value={cfg('log_level') || 'info'}
                            onChange={e => saveGeneral('log_level', e.target.value)}
                        >
                            {LOG_LEVELS.map(l => (
                                <option key={l} value={l}>
                                    {l.toUpperCase()}
                                </option>
                            ))}
                        </InsetSelect>
                    </div>
                    <Divider />
                    <div className="flex flex-wrap items-center justify-between gap-4 py-2">
                        <RowLabel label="Retention" hint="Delete rotated logs older than" />
                        <InsetSelect
                            ariaLabel="Log retention"
                            value={cfg('log_retention_days') ?? 0}
                            onChange={e =>
                                saveGeneral('log_retention_days', Number(e.target.value))
                            }
                        >
                            {RETENTION_OPTIONS.map(o => (
                                <option key={o.value} value={o.value}>
                                    {o.label}
                                </option>
                            ))}
                        </InsetSelect>
                    </div>
                </Section>

                {/* BACKUPS & DATABASE */}
                <Section title="Backups & database">
                    <div className="flex flex-wrap items-center justify-between gap-4 py-2">
                        <RowLabel
                            label="Automatic config backups"
                            hint={
                                lastBackup
                                    ? `Last backup ${timeAgo(lastBackup.created) || '—'} · ${backups.length} kept`
                                    : 'No backups yet'
                            }
                        />
                        <Toggle
                            label="Automatic config backups"
                            checked={!!cfg('auto_backup')}
                            onChange={v => saveGeneral('auto_backup', v)}
                        />
                    </div>
                    <Divider />
                    <div className="flex flex-wrap items-center justify-between gap-4 py-2">
                        <RowLabel
                            label="Backup location"
                            hint="Blank uses the config directory — which is the same volume as the data it protects"
                        />
                        <InsetInput
                            ariaLabel="Backup location"
                            placeholder="/mnt/user/backups/chub"
                            value={backupDir}
                            onChange={e => setBackupDir(e.target.value)}
                            onBlur={() => {
                                const next = backupDir.trim();
                                if (next !== (general.backup_dir || '')) {
                                    saveGeneral('backup_dir', next);
                                }
                            }}
                        />
                    </div>
                    <Divider />
                    <div className="flex flex-wrap items-center justify-between gap-4 py-2">
                        <RowLabel
                            label="Manual backup"
                            hint="Download or restore a config + database archive"
                        />
                        <div className="flex items-center gap-2 shrink-0">
                            <LoadingButton
                                loading={backingUp}
                                loadingText="Backing up…"
                                variant="secondary"
                                size="small"
                                icon="download"
                                onClick={handleBackup}
                            >
                                Back up
                            </LoadingButton>
                            <Button
                                variant="ghost"
                                size="small"
                                icon="upload"
                                disabled={restoring}
                                onClick={() => restoreInputRef.current?.click()}
                            >
                                {restoring ? 'Restoring…' : 'Restore'}
                            </Button>
                            <input
                                ref={restoreInputRef}
                                type="file"
                                accept=".zip"
                                className="hidden"
                                onChange={handleRestoreFile}
                            />
                        </div>
                    </div>
                    <Divider />
                    <div className="flex flex-wrap items-center justify-between gap-4 py-2">
                        <RowLabel
                            label="Database"
                            hint={`chub.db · ${formatBytes(dbFileBytes)}${
                                stats.free_bytes > 1024 * 1024
                                    ? ` · ${formatBytes(stats.free_bytes)} reclaimable`
                                    : ''
                            }`}
                            mono
                        />
                        <LoadingButton
                            loading={vacuuming}
                            loadingText="Vacuuming…"
                            variant="secondary"
                            size="small"
                            icon="compress"
                            onClick={handleVacuum}
                        >
                            Vacuum
                        </LoadingButton>
                    </div>
                    <Divider />
                    <button
                        type="button"
                        onClick={() => setShowDbDetails(s => !s)}
                        className="flex items-center gap-1.5 pt-2 text-[12.5px] text-fg-subtle hover:text-fg"
                    >
                        <span
                            className="material-symbols-outlined text-[18px] transition-transform"
                            style={{ transform: showDbDetails ? 'rotate(90deg)' : 'none' }}
                            aria-hidden="true"
                        >
                            chevron_right
                        </span>
                        {showDbDetails ? 'Hide' : 'Show'} database details — {tables.length} tables
                        · {formatNumber(totalRows)} rows · {migrations.length} migrations
                    </button>
                    {showDbDetails && (
                        <div className="mt-3 flex flex-col gap-4">
                            <div className="overflow-x-auto rounded-lg border border-border">
                                <table className="w-full text-sm">
                                    <thead>
                                        <tr className="bg-surface-inset text-fg-faint text-left font-mono text-[10px] uppercase tracking-[1px]">
                                            <th className="px-3 py-2 font-medium">Table</th>
                                            <th className="px-3 py-2 font-medium text-right">
                                                Rows
                                            </th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-border-light">
                                        {tables.map(t => (
                                            <tr key={t.name} className="hover:bg-row-hover">
                                                <td className="px-3 py-1.5 text-fg font-mono text-xs">
                                                    {t.name}
                                                </td>
                                                <td className="px-3 py-1.5 text-right text-fg-muted font-mono text-xs">
                                                    {formatNumber(t.rows)}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                            {migrations.length > 0 && (
                                <div className="overflow-x-auto rounded-lg border border-border">
                                    <table className="w-full text-sm">
                                        <thead>
                                            <tr className="bg-surface-inset text-fg-faint text-left font-mono text-[10px] uppercase tracking-[1px]">
                                                <th className="px-3 py-2 font-medium">Migration</th>
                                                <th className="px-3 py-2 font-medium">Applied</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-border-light">
                                            {migrations.map(m => (
                                                <tr key={m.name} className="hover:bg-row-hover">
                                                    <td className="px-3 py-1.5 text-fg font-mono text-xs">
                                                        {m.name}
                                                    </td>
                                                    <td className="px-3 py-1.5 text-fg-muted text-xs">
                                                        {formatDateTime(m.applied_at)}
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                            {isMobile && (
                                <p className="text-xs text-fg-subtle">
                                    Tip: rotate your device for a wider table view.
                                </p>
                            )}
                        </div>
                    )}
                </Section>

                {/* DANGER ZONE */}
                <Section title="Danger zone" titleColor="text-error" tone="danger">
                    <p className="text-[12.5px] text-fg-subtle -mt-2 mb-3.5">
                        This action cannot be undone.
                    </p>
                    <button
                        type="button"
                        onClick={() => setConfirmClearPoster(true)}
                        className="h-9 px-3.5 rounded-lg bg-transparent border border-error/35 text-error text-[12.5px] font-semibold hover:bg-error/10 transition-colors"
                    >
                        Clear poster cache
                    </button>
                </Section>
            </div>

            <Modal
                isOpen={confirmClearPoster}
                onClose={() => setConfirmClearPoster(false)}
                size="small"
            >
                <Modal.Header>Clear poster cache?</Modal.Header>
                <Modal.Body>
                    <p className="text-fg-muted">
                        This deletes every row in <code>poster_cache</code> (currently{' '}
                        <span className="font-semibold text-fg">{formatNumber(posterRows)}</span>{' '}
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
                        Clear cache
                    </LoadingButton>
                </Modal.Footer>
            </Modal>
        </div>
    );
};

export default SystemSettingsPage;
