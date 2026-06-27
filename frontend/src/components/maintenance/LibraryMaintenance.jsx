import React, { useState } from 'react';
import { useApiMutation } from '../../hooks/useApiData.js';
import { mediaAPI } from '../../utils/api/media.js';
import { Modal } from '../modals/Modal';
import { Button, LoadingButton } from '../ui/index.js';

const MaintenanceCard = ({
    title,
    icon,
    iconClass = 'text-warning',
    count,
    countClass = 'bg-warning/15 text-warning',
    description,
    children,
    defaultOpen = false,
}) => {
    const [open, setOpen] = useState(defaultOpen);
    return (
        <div className="rounded-xl bg-surface border border-border overflow-hidden">
            <button
                type="button"
                onClick={() => setOpen(o => !o)}
                className="w-full flex items-center gap-3.5 px-5 py-4 text-left cursor-pointer bg-transparent border-0 transition-colors hover:bg-row-hover"
                aria-expanded={open}
            >
                <span className={`material-symbols-outlined text-[22px] ${iconClass}`}>{icon}</span>
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2.5">
                        <span className="font-display text-base font-semibold text-fg">
                            {title}
                        </span>
                        {count != null && (
                            <span
                                className={`font-mono text-[10px] font-semibold px-2 py-0.5 rounded-full ${countClass}`}
                            >
                                {count}
                            </span>
                        )}
                    </div>
                    <div className="text-[12.5px] text-fg-subtle mt-0.5">{description}</div>
                </div>
                <span
                    className="material-symbols-outlined text-fg-subtle transition-transform"
                    style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)' }}
                >
                    chevron_right
                </span>
            </button>
            {open && (
                <div className="px-5 pt-3.5 pb-4 border-t border-border-light">{children}</div>
            )}
        </div>
    );
};

const OrphanedCacheCard = () => {
    const [data, setData] = useState(null);
    const [selected, setSelected] = useState(new Set());
    const [confirmPurge, setConfirmPurge] = useState(false);

    const { execute: runCheck, isLoading: isChecking } = useApiMutation(
        async () => {
            const result = await mediaAPI.fetchOrphaned();
            setData(result?.data || null);
            setSelected(new Set());
            return result;
        },
        { successMessage: 'Orphaned cache check complete' }
    );

    const { execute: runPurge, isLoading: isPurging } = useApiMutation(
        ids => mediaAPI.purgeOrphaned(ids),
        {
            successMessage: 'Orphaned rows purged',
            onSuccess: () => {
                setConfirmPurge(false);
                runCheck();
            },
        }
    );

    const items = data?.items || [];
    const allSelected = items.length > 0 && selected.size === items.length;
    const toggleAll = () => setSelected(allSelected ? new Set() : new Set(items.map(i => i.id)));
    const toggleOne = id =>
        setSelected(s => {
            const next = new Set(s);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });

    return (
        <MaintenanceCard
            title="Orphaned cache rows"
            icon="link_off"
            iconClass="text-warning"
            count={data ? `${items.length} rows` : undefined}
            countClass="bg-warning/15 text-warning"
            description="Items in CHUB's local cache whose ARR entry no longer exists. Purging only removes the cache row; ARR and disk are untouched."
            defaultOpen
        >
            <div className="flex flex-wrap items-center gap-2 mb-3">
                <LoadingButton
                    loading={isChecking}
                    loadingText="Checking..."
                    variant="ghost"
                    icon="radar"
                    onClick={runCheck}
                >
                    Refresh check
                </LoadingButton>
                {data && (
                    <>
                        <span className="text-sm text-fg-muted">
                            {items.length} orphaned · instances checked:{' '}
                            {(data.instances_checked || []).join(', ') || 'none'}
                        </span>
                        {selected.size > 0 && (
                            <LoadingButton
                                loading={isPurging}
                                loadingText="Purging..."
                                variant="danger"
                                icon="delete"
                                onClick={() => setConfirmPurge(true)}
                                className="sm:ml-auto"
                            >
                                Purge {selected.size} selected
                            </LoadingButton>
                        )}
                    </>
                )}
            </div>
            {items.length > 0 && (
                <div className="rounded bg-surface-alt">
                    <div className="flex items-center gap-2 p-2 border-b border-border text-xs text-fg-subtle">
                        <input type="checkbox" checked={allSelected} onChange={toggleAll} />
                        <span>Select all</span>
                    </div>
                    <div
                        className="flex flex-col divide-y divide-border overflow-y-auto"
                        style={{ maxHeight: '24rem' }}
                    >
                        {items.map(row => (
                            <label
                                key={row.id}
                                className="flex items-center gap-2 p-2 cursor-pointer hover:bg-surface"
                            >
                                <input
                                    type="checkbox"
                                    checked={selected.has(row.id)}
                                    onChange={() => toggleOne(row.id)}
                                />
                                <span className="flex-1 min-w-0 truncate text-fg text-sm">
                                    {row.title}
                                </span>
                                <span className="text-xs text-fg-subtle capitalize">
                                    {row.asset_type}
                                </span>
                                <span className="text-xs text-fg-subtle">{row.instance_name}</span>
                                <span className="text-xs text-fg-subtle font-mono">
                                    arr_id {row.arr_id}
                                </span>
                            </label>
                        ))}
                    </div>
                </div>
            )}
            {data && items.length === 0 && (
                <div className="text-sm text-fg-muted">No orphaned rows found.</div>
            )}

            <Modal isOpen={confirmPurge} onClose={() => setConfirmPurge(false)} size="small">
                <Modal.Header>Purge {selected.size} cache row(s)?</Modal.Header>
                <Modal.Body>
                    <p className="text-sm text-fg-muted">
                        These rows will be removed from CHUB&apos;s local cache only. Nothing is
                        deleted from Radarr, Sonarr, Lidarr, or disk.
                    </p>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="ghost" onClick={() => setConfirmPurge(false)}>
                        Cancel
                    </Button>
                    <LoadingButton
                        loading={isPurging}
                        loadingText="Purging..."
                        variant="danger"
                        onClick={() => runPurge([...selected])}
                    >
                        Purge
                    </LoadingButton>
                </Modal.Footer>
            </Modal>
        </MaintenanceCard>
    );
};

const INCOMPLETE_FIELDS = [
    { key: 'tmdb_id', label: 'TMDB id' },
    { key: 'tvdb_id', label: 'TVDB id' },
    { key: 'imdb_id', label: 'IMDB id' },
    { key: 'year', label: 'Year' },
    { key: 'rating', label: 'Rating' },
    { key: 'studio', label: 'Studio' },
    { key: 'language', label: 'Language' },
    { key: 'runtime', label: 'Runtime' },
    { key: 'genre', label: 'Genre' },
];

const IncompleteMetadataCard = () => {
    const [data, setData] = useState(null);
    const [fields, setFields] = useState(new Set(['tmdb_id', 'tvdb_id', 'imdb_id', 'year']));

    const { execute: runCheck, isLoading: isChecking } = useApiMutation(async () => {
        const result = await mediaAPI.fetchIncompleteMetadata({
            fields: [...fields].join(','),
        });
        setData(result?.data || null);
        return result;
    });

    const items = data?.items || [];
    const toggleField = name =>
        setFields(s => {
            const next = new Set(s);
            if (next.has(name)) next.delete(name);
            else next.add(name);
            return next;
        });

    // Backend returns `missing` pre-filtered for fields that asset_type
    // never populates (radarr has no tvdb_id, lidarr has no tmdb/tvdb/imdb,
    // etc). Fall back to a client compute for older backends.
    const whatsMissing = row => {
        if (Array.isArray(row.missing)) return row.missing.join(', ');
        return [...fields].filter(f => !row[f] || row[f] === 0 || row[f] === '').join(', ');
    };

    return (
        <MaintenanceCard
            title="Incomplete metadata"
            icon="rule"
            iconClass="text-[#ff9d75]"
            count={data ? `${items.length} items` : undefined}
            countClass="bg-[#ff9d75]/15 text-[#ff9d75]"
            description="Items missing key fields. External IDs (TMDB/TVDB/IMDB) missing → Poster Renamerr and Border Replacerr can't match them. Fix in the origin ARR."
        >
            <div className="flex flex-wrap gap-2 mb-3">
                {INCOMPLETE_FIELDS.map(f => {
                    const active = fields.has(f.key);
                    return (
                        <button
                            key={f.key}
                            type="button"
                            onClick={() => toggleField(f.key)}
                            className="px-3 py-1.5 rounded-full text-sm cursor-pointer"
                            style={{
                                background: active
                                    ? 'color-mix(in srgb, var(--accent) 18%, transparent)'
                                    : 'var(--surface-alt)',
                                border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
                                color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
                            }}
                        >
                            {f.label}
                        </button>
                    );
                })}
            </div>
            <div className="flex flex-wrap items-center gap-2 mb-3">
                <LoadingButton
                    loading={isChecking}
                    loadingText="Checking..."
                    variant="ghost"
                    icon="radar"
                    onClick={runCheck}
                    disabled={fields.size === 0}
                >
                    Refresh check
                </LoadingButton>
                {data && <span className="text-sm text-fg-muted">{items.length} item(s)</span>}
            </div>
            {items.length > 0 && (
                <div className="rounded bg-surface-alt">
                    <div
                        className="flex flex-col divide-y divide-border overflow-y-auto"
                        style={{ maxHeight: '24rem' }}
                    >
                        {items.map(row => (
                            <div key={row.id} className="flex items-center gap-2 p-2">
                                <span className="flex-1 min-w-0 truncate text-fg text-sm">
                                    {row.title}
                                    {row.year ? ` (${row.year})` : ''}
                                </span>
                                <span className="text-xs text-fg-subtle capitalize">
                                    {row.asset_type}
                                </span>
                                <span className="text-xs text-fg-subtle">{row.instance_name}</span>
                                <span className="text-xs text-warning">
                                    missing: {whatsMissing(row) || '—'}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}
            {data && items.length === 0 && (
                <div className="text-sm text-fg-muted">No items missing the selected fields.</div>
            )}
        </MaintenanceCard>
    );
};

export const LibraryMaintenance = () => (
    <section className="mt-9">
        <div className="flex items-center gap-3 mb-3.5">
            <span className="material-symbols-outlined text-[22px] text-[#a99eff]">handyman</span>
            <h2 className="font-display text-xl font-bold text-fg">Library Maintenance</h2>
        </div>
        <div className="flex flex-col gap-3">
            <OrphanedCacheCard />
            <IncompleteMetadataCard />
        </div>
    </section>
);

export default LibraryMaintenance;
