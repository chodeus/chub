import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useApiData, useApiMutation } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { useUnsavedChangesWarning } from '../../hooks/useUnsavedChangesWarning';
import { labelarrAPI } from '../../utils/api/labelarr.js';
import { modulesAPI } from '../../utils/api/modules.js';
import { configAPI } from '../../utils/api/config.js';
import { instancesAPI } from '../../utils/api';
import { Button, IconButton, LoadingButton, StatusDot, Toggle } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';
import { formatDateTime } from '../../utils/datetime.js';
import { formatTimeAgo } from '../../utils/schedule.js';

// labels may be stored as a JSON-ish list or a comma string — normalise to a
// clean array.
function toLabelList(labels) {
    if (Array.isArray(labels)) return labels.filter(Boolean);
    if (typeof labels === 'string' && labels.trim()) {
        return labels
            .split(',')
            .map(s => s.trim())
            .filter(Boolean);
    }
    return [];
}

// Normalise a raw config mapping into the working shape (+ a stable local key).
let _uid = 0;
function normalizeMapping(m) {
    return {
        _key: `m${_uid++}`,
        app_instance: m.app_instance || '',
        labels: toLabelList(m.labels),
        plex_instances: (m.plex_instances || []).map(p => ({
            instance: p.instance || '',
            library_names: Array.isArray(p.library_names)
                ? p.library_names.filter(Boolean)
                : toLabelList(p.library_names),
        })),
        enabled: m.enabled !== false,
    };
}

// Strip the local key before persisting.
function toConfigMapping(m) {
    return {
        app_instance: m.app_instance,
        labels: m.labels,
        plex_instances: m.plex_instances.map(p => ({
            instance: p.instance,
            library_names: p.library_names,
        })),
        enabled: m.enabled,
    };
}

const arrDotColor = type => (type === 'sonarr' ? '#53e8f0' : '#6cbc66');

const LabelarrPage = () => {
    const toast = useToast();

    // Run state drives the stats strip (status + last sync).
    const { data: statusData, refresh: refreshStatus } = useApiData({
        apiFunction: modulesAPI.fetchRunStates,
        options: { showErrorToast: false },
    });
    const labelarrState = useMemo(() => statusData?.data?.labelarr || null, [statusData]);

    // Full config (no cache) so we can splice mappings back in on save.
    const [fullConfig, setFullConfig] = useState(null);
    const [mappings, setMappings] = useState(null);
    const [baseline, setBaseline] = useState('');
    const [isLoading, setIsLoading] = useState(true);
    const [loadError, setLoadError] = useState(null);
    const [isSaving, setIsSaving] = useState(false);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const resp = await configAPI.fetchConfig({ useCache: false });
                if (cancelled) return;
                const cfg = resp?.data || {};
                const normalized = (cfg.labelarr?.mappings || []).map(normalizeMapping);
                setFullConfig(cfg);
                setMappings(normalized);
                setBaseline(JSON.stringify(normalized.map(toConfigMapping)));
            } catch (err) {
                if (!cancelled) setLoadError(err.message || 'Failed to load configuration');
            } finally {
                if (!cancelled) setIsLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);

    const isDirty = useMemo(
        () => (mappings ? JSON.stringify(mappings.map(toConfigMapping)) !== baseline : false),
        [mappings, baseline]
    );
    useUnsavedChangesWarning(isDirty);

    const { execute: runSync, isLoading: isSyncing } = useApiMutation(() => labelarrAPI.sync(), {
        successMessage: 'Label sync initiated',
        onSuccess: () => refreshStatus(),
    });

    // ─── ARR / Plex instance options for the editor dropdowns ──────────
    const arrOptions = useMemo(() => {
        const inst = fullConfig?.instances || {};
        const out = [];
        for (const name of Object.keys(inst.radarr || {})) out.push({ name, type: 'radarr' });
        for (const name of Object.keys(inst.sonarr || {})) out.push({ name, type: 'sonarr' });
        return out;
    }, [fullConfig]);
    const plexOptions = useMemo(() => Object.keys(fullConfig?.instances?.plex || {}), [fullConfig]);
    const arrType = useCallback(
        name => arrOptions.find(a => a.name === name)?.type || 'radarr',
        [arrOptions]
    );

    // ─── Mutators ──────────────────────────────────────────────────────
    const updateMapping = useCallback((key, patch) => {
        setMappings(prev => prev.map(m => (m._key === key ? { ...m, ...patch } : m)));
    }, []);
    const addMapping = useCallback(() => {
        setMappings(prev => [
            ...prev,
            normalizeMapping({ app_instance: arrOptions[0]?.name || '', labels: [] }),
        ]);
    }, [arrOptions]);
    const removeMapping = useCallback(key => {
        setMappings(prev => prev.filter(m => m._key !== key));
    }, []);

    const handleSave = useCallback(async () => {
        if (!fullConfig || !mappings || !isDirty || isSaving) return;
        setIsSaving(true);
        try {
            const next = {
                ...fullConfig,
                labelarr: {
                    ...(fullConfig.labelarr || {}),
                    mappings: mappings.map(toConfigMapping),
                },
            };
            await configAPI.updateConfig(next);
            setFullConfig(next);
            setBaseline(JSON.stringify(mappings.map(toConfigMapping)));
            toast.success('Label mappings saved');
        } catch (err) {
            toast.error(err.message || 'Failed to save mappings');
        } finally {
            setIsSaving(false);
        }
    }, [fullConfig, mappings, isDirty, isSaving, toast]);

    const handleDiscard = useCallback(() => {
        if (!isDirty) return;
        if (!window.confirm('Discard unsaved mapping changes?')) return;
        try {
            setMappings(JSON.parse(baseline).map(normalizeMapping));
        } catch {
            /* baseline is always our own JSON; defensive only */
        }
    }, [baseline, isDirty]);

    // Cmd/Ctrl+S → save.
    useEffect(() => {
        const onKey = e => {
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's' && isDirty && !isSaving) {
                e.preventDefault();
                handleSave();
            }
        };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [handleSave, isDirty, isSaving]);

    // ─── Stats strip ───────────────────────────────────────────────────
    const status = labelarrState?.status || 'idle';
    const enabledCount = useMemo(() => (mappings || []).filter(m => m.enabled).length, [mappings]);
    const labelCount = useMemo(
        () => (mappings || []).reduce((sum, m) => sum + (m.enabled ? m.labels.length : 0), 0),
        [mappings]
    );

    if (isLoading) return <Spinner size="large" text="Loading labelarr config…" center />;
    if (loadError) {
        return (
            <div className="p-3 bg-error/10 border border-error/30 text-error rounded-lg">
                {loadError}
            </div>
        );
    }

    const stats = [
        {
            label: 'MAPPINGS',
            value: `${enabledCount}/${mappings.length}`,
            tone: 'text-fg',
        },
        { label: 'LABELS', value: labelCount, tone: 'text-success' },
        {
            label: 'STATUS',
            value: status,
            capitalize: true,
            tone:
                status === 'success'
                    ? 'text-success'
                    : status === 'error'
                      ? 'text-error'
                      : status === 'running'
                        ? 'text-accent'
                        : 'text-fg-muted',
        },
        {
            label: 'LAST SYNC',
            value: labelarrState?.last_run
                ? formatTimeAgo(labelarrState.last_run, new Date())
                : 'Never',
            tone: 'text-fg-muted',
            title: labelarrState?.last_run ? formatDateTime(labelarrState.last_run) : undefined,
        },
    ];

    return (
        <div className="flex flex-col gap-5">
            {/* Toolbar */}
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                    <h1 className="font-display text-[26px] font-bold tracking-[-0.3px] text-fg m-0">
                        Label Sync
                    </h1>
                    <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">
                        Mirror Radarr / Sonarr tags onto Plex labels · managed by{' '}
                        <span className="font-mono text-fg-muted">labelarr</span>
                        {fullConfig?.labelarr?.dry_run && (
                            <span className="ml-2 font-mono text-[10px] px-2 py-0.5 rounded-full bg-warning/15 text-warning align-middle">
                                DRY RUN
                            </span>
                        )}
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2.5">
                    {isDirty && (
                        <span className="inline-flex items-center gap-1 font-mono text-[11px] px-2.5 py-1 rounded-full bg-warning/15 text-warning">
                            <span className="material-symbols-outlined text-[14px]">edit</span>
                            Unsaved
                        </span>
                    )}
                    <Button
                        variant="surface"
                        icon="undo"
                        onClick={handleDiscard}
                        disabled={!isDirty || isSaving}
                    >
                        Discard
                    </Button>
                    <LoadingButton
                        variant="surface"
                        icon="sync"
                        onClick={() => runSync()}
                        isLoading={isSyncing}
                    >
                        Sync now
                    </LoadingButton>
                    <LoadingButton
                        variant="primary"
                        icon="save"
                        onClick={handleSave}
                        loading={isSaving}
                        disabled={!isDirty}
                    >
                        Save
                    </LoadingButton>
                </div>
            </div>

            {/* Stats strip */}
            <div
                className="flex items-stretch flex-wrap bg-surface border border-border rounded-xl overflow-hidden"
                style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
            >
                {stats.map((s, i) => (
                    <React.Fragment key={s.label}>
                        {i > 0 && (
                            <div className="hidden sm:block w-px self-stretch bg-border my-3" />
                        )}
                        <div className="px-4 sm:px-[22px] py-3.5 flex flex-col gap-1.5 min-w-[116px] flex-1">
                            <span className="font-mono text-[10px] tracking-[1.2px] text-fg-subtle">
                                {s.label}
                            </span>
                            <span
                                className={`font-mono font-semibold text-[18px] ${s.tone} ${s.capitalize ? 'capitalize' : ''}`}
                                title={s.title}
                            >
                                {s.value}
                            </span>
                        </div>
                    </React.Fragment>
                ))}
            </div>

            {labelarrState?.message && (
                <div className="text-[12.5px] text-fg-muted bg-surface border border-border rounded-lg px-4 py-3">
                    {labelarrState.message}
                </div>
            )}

            {/* Mappings editor */}
            <div className="flex items-center justify-between">
                <h2 className="font-display text-[15px] font-semibold text-fg m-0">Mappings</h2>
                <Button variant="surface" size="small" icon="add" onClick={addMapping}>
                    Add mapping
                </Button>
            </div>

            {mappings.length === 0 ? (
                <div className="bg-surface border border-dashed border-border rounded-xl px-5 py-10 text-center">
                    <span className="material-symbols-outlined text-3xl text-fg-subtle block mb-2">
                        label
                    </span>
                    <p className="text-sm text-fg-muted m-0">No label mappings yet.</p>
                    <p className="text-xs text-fg-subtle mt-1 mb-0">
                        Add a mapping to mirror an *arr instance&apos;s tags onto Plex labels.
                    </p>
                </div>
            ) : (
                <div className="flex flex-col gap-3">
                    {mappings.map(m => (
                        <MappingCard
                            key={m._key}
                            mapping={m}
                            arrOptions={arrOptions}
                            plexOptions={plexOptions}
                            arrType={arrType}
                            disabled={isSaving}
                            onChange={patch => updateMapping(m._key, patch)}
                            onRemove={() => removeMapping(m._key)}
                        />
                    ))}
                </div>
            )}

            {arrOptions.length === 0 && (
                <p className="text-xs text-fg-subtle">
                    No Radarr/Sonarr instances configured — add one in Settings → Instances to map
                    its tags.
                </p>
            )}
        </div>
    );
};

// ─── Mapping card (collapsed summary + expandable editor) ───────────────
// Compact multi-select of a Plex instance's OPTED-IN libraries. Replaces the
// old free-text field so a user can only target libraries enabled on
// Settings → Instances (the list endpoint annotates each with `enabled`).
// No ticks = all enabled libraries (the labelarr backend's "empty = all").
const libNorm = t => (t || '').trim().toLowerCase();

const LabelarrLibraryPicker = ({ instanceName, value, onChange, disabled }) => {
    const { data, isLoading } = useApiData({
        apiFunction: () => instancesAPI.fetchPlexLibraries(instanceName),
        dependencies: [instanceName],
        options: { immediate: !!instanceName, showErrorToast: false },
    });

    const libraries = useMemo(() => {
        const raw = data?.data?.libraries;
        if (!Array.isArray(raw)) return [];
        return raw
            .filter(l => typeof l === 'string' || l.enabled !== false)
            .map(l => (typeof l === 'string' ? l : l.title))
            .filter(Boolean);
    }, [data]);

    const selected = useMemo(() => new Set((value || []).map(libNorm)), [value]);

    const hint = 'self-center text-xs text-fg-subtle';
    if (!instanceName) {
        return <span className={hint}>Select a Plex instance first</span>;
    }
    if (isLoading) {
        return <span className={hint}>Loading libraries…</span>;
    }
    if (libraries.length === 0) {
        return (
            <span className={hint}>No enabled libraries — opt some in on Settings → Instances</span>
        );
    }

    const toggle = title => {
        const on = selected.has(libNorm(title));
        onChange(
            on
                ? (value || []).filter(v => libNorm(v) !== libNorm(title))
                : [...(value || []), title]
        );
    };

    return (
        <div className="flex flex-wrap gap-1.5 py-1">
            {libraries.map(title => {
                const on = selected.has(libNorm(title));
                return (
                    <button
                        key={title}
                        type="button"
                        disabled={disabled}
                        aria-pressed={on}
                        onClick={() => toggle(title)}
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-[5px] text-xs border transition-colors disabled:opacity-50 ${
                            on
                                ? 'bg-primary/15 border-primary text-fg'
                                : 'bg-surface-inset border-border text-fg-muted hover:border-primary'
                        }`}
                    >
                        {title}
                    </button>
                );
            })}
            {selected.size === 0 && (
                <span className="self-center text-[11px] text-fg-subtle">
                    none ticked = all enabled
                </span>
            )}
        </div>
    );
};

const MappingCard = ({
    mapping,
    arrOptions,
    plexOptions,
    arrType,
    disabled,
    onChange,
    onRemove,
}) => {
    const [expanded, setExpanded] = useState(!mapping.app_instance);
    const inputCls =
        'h-9 rounded-[8px] bg-surface-inset border border-border text-fg text-[13px] px-3 outline-none focus:border-primary disabled:opacity-50';

    const setLabels = useCallback(
        v =>
            onChange({
                labels: v
                    .split(',')
                    .map(s => s.trim())
                    .filter(Boolean),
            }),
        [onChange]
    );

    const updatePlex = (idx, patch) =>
        onChange({
            plex_instances: mapping.plex_instances.map((p, i) =>
                i === idx ? { ...p, ...patch } : p
            ),
        });
    const addPlex = () =>
        onChange({
            plex_instances: [
                ...mapping.plex_instances,
                { instance: plexOptions[0] || '', library_names: [] },
            ],
        });
    const removePlex = idx =>
        onChange({ plex_instances: mapping.plex_instances.filter((_, i) => i !== idx) });

    return (
        <section
            className={`bg-surface border border-border rounded-xl overflow-hidden ${mapping.enabled ? '' : 'opacity-60'}`}
        >
            {/* Header */}
            <div className="flex items-center gap-3 px-4 py-3">
                <Toggle
                    checked={mapping.enabled}
                    onChange={v => onChange({ enabled: v })}
                    disabled={disabled}
                    label={`Enable mapping for ${mapping.app_instance || 'new mapping'}`}
                />
                <button
                    type="button"
                    onClick={() => setExpanded(v => !v)}
                    className="flex items-center gap-3 flex-1 min-w-0 text-left bg-transparent border-0 cursor-pointer p-0"
                    aria-expanded={expanded}
                >
                    <StatusDot
                        color={arrDotColor(arrType(mapping.app_instance))}
                        ring={false}
                        size={7}
                    />
                    <span className="font-mono text-[13px] font-semibold text-fg truncate">
                        {mapping.app_instance || '(no instance)'}
                    </span>
                    <span className="material-symbols-outlined text-[16px] text-fg-dim">
                        arrow_forward
                    </span>
                    <span className="flex items-center gap-1.5 flex-wrap min-w-0">
                        {mapping.labels.length === 0 ? (
                            <span className="text-xs text-fg-subtle italic">no labels</span>
                        ) : (
                            mapping.labels.slice(0, 4).map(l => (
                                <span
                                    key={l}
                                    className="font-mono text-[10.5px] px-2 py-0.5 rounded-[5px] bg-warning/15 text-warning"
                                >
                                    {l}
                                </span>
                            ))
                        )}
                        {mapping.labels.length > 4 && (
                            <span className="font-mono text-[10.5px] text-fg-subtle">
                                +{mapping.labels.length - 4}
                            </span>
                        )}
                    </span>
                    <span className="ml-auto font-mono text-[11px] text-fg-subtle truncate hidden md:inline">
                        {mapping.plex_instances.length
                            ? mapping.plex_instances
                                  .map(p => p.instance)
                                  .filter(Boolean)
                                  .join(', ')
                            : 'no plex target'}
                    </span>
                    <span
                        className="material-symbols-outlined text-fg-subtle transition-transform"
                        style={{ transform: expanded ? 'rotate(180deg)' : 'none' }}
                    >
                        expand_more
                    </span>
                </button>
                <IconButton
                    icon="delete"
                    variant="ghost"
                    size="small"
                    aria-label="Remove mapping"
                    onClick={onRemove}
                    disabled={disabled}
                />
            </div>

            {/* Editor */}
            {expanded && (
                <div className="px-4 pb-4 pt-1 border-t border-border-light flex flex-col gap-4">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <label className="flex flex-col gap-1.5">
                            <span className="font-mono text-[10px] tracking-[0.5px] text-fg-faint uppercase">
                                ARR instance
                            </span>
                            <select
                                value={mapping.app_instance}
                                onChange={e => onChange({ app_instance: e.target.value })}
                                disabled={disabled}
                                className={inputCls}
                            >
                                <option value="">Select instance…</option>
                                {arrOptions.map(a => (
                                    <option key={a.name} value={a.name}>
                                        {a.name} ({a.type})
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label className="flex flex-col gap-1.5">
                            <span className="font-mono text-[10px] tracking-[0.5px] text-fg-faint uppercase">
                                Tags / labels (comma-separated)
                            </span>
                            <input
                                type="text"
                                value={mapping.labels.join(', ')}
                                onChange={e => setLabels(e.target.value)}
                                placeholder="e.g. 4k, anime, kids"
                                disabled={disabled}
                                className={inputCls}
                            />
                        </label>
                    </div>

                    {/* Plex targets */}
                    <div className="flex flex-col gap-2">
                        <div className="flex items-center justify-between">
                            <span className="font-mono text-[10px] tracking-[0.5px] text-fg-faint uppercase">
                                Plex targets
                            </span>
                            <Button
                                variant="ghost"
                                size="small"
                                icon="add"
                                onClick={addPlex}
                                disabled={disabled || plexOptions.length === 0}
                            >
                                Add target
                            </Button>
                        </div>
                        {mapping.plex_instances.length === 0 ? (
                            <p className="text-xs text-fg-subtle m-0">
                                {plexOptions.length === 0
                                    ? 'No Plex instances configured — add one in Settings → Instances.'
                                    : 'No Plex target yet — add one to choose which libraries get labelled.'}
                            </p>
                        ) : (
                            mapping.plex_instances.map((p, idx) => (
                                <div
                                    key={idx}
                                    className="grid grid-cols-1 sm:grid-cols-[200px_1fr_auto] gap-2 items-start"
                                >
                                    <select
                                        value={p.instance}
                                        onChange={e =>
                                            updatePlex(idx, {
                                                instance: e.target.value,
                                                // A different server has different
                                                // libraries — drop the stale picks.
                                                library_names: [],
                                            })
                                        }
                                        disabled={disabled}
                                        className={inputCls}
                                    >
                                        <option value="">Select Plex…</option>
                                        {plexOptions.map(name => (
                                            <option key={name} value={name}>
                                                {name}
                                            </option>
                                        ))}
                                    </select>
                                    <LabelarrLibraryPicker
                                        instanceName={p.instance}
                                        value={p.library_names}
                                        onChange={names =>
                                            updatePlex(idx, { library_names: names })
                                        }
                                        disabled={disabled}
                                    />
                                    <IconButton
                                        icon="close"
                                        variant="ghost"
                                        size="small"
                                        aria-label="Remove Plex target"
                                        onClick={() => removePlex(idx)}
                                        disabled={disabled}
                                    />
                                </div>
                            ))
                        )}
                    </div>
                </div>
            )}
        </section>
    );
};

export default LabelarrPage;
