import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Link, useParams } from 'react-router';
import { configAPI } from '../../../utils/api/config.js';
import { modulesAPI } from '../../../utils/api/modules.js';
import { SETTINGS_MODULES } from '../../../utils/constants/settings_schema.js';
import { useModuleSchema } from '../../../hooks/useModuleSchema.js';
import { shouldShowField } from '../../../utils/forms/conditionalFields.js';
import { useInstancesData } from '../../../hooks/useInstancesData.js';
import { FieldRegistry } from '../../../components/fields/FieldRegistry.jsx';
import { ConfigProvider, useConfig } from '../../../contexts/ConfigContext.jsx';
import { useToast } from '../../../contexts/ToastContext.jsx';
import { useUnsavedChangesWarning } from '../../../hooks/useUnsavedChangesWarning';
import Toggle from '../../../components/ui/Toggle.jsx';
import SegmentedControl from '../../../components/ui/SegmentedControl.jsx';
import InfoTooltip from '../../../components/ui/InfoTooltip.jsx';

/**
 * Memoized field component — only re-renders when value/key/disabled change.
 */
const MemoizedFieldComponent = React.memo(
    ({ field, value, onChange, ...props }) => {
        const fieldComponent = FieldRegistry.getField(field.type);
        if (!fieldComponent) {
            return (
                <div className="p-2 bg-warning-bg text-warning rounded">
                    Unknown field type: {field.type}
                </div>
            );
        }
        return React.createElement(fieldComponent, { field, value, onChange, ...props });
    },
    (prevProps, nextProps) =>
        prevProps.value === nextProps.value &&
        prevProps.field.key === nextProps.field.key &&
        prevProps.disabled === nextProps.disabled &&
        prevProps.highlightInvalid === nextProps.highlightInvalid
);
MemoizedFieldComponent.displayName = 'MemoizedFieldComponent';

/**
 * Scoped per-module config page (settings/modules/:moduleKey) — the redesign's
 * module-settings shell: breadcrumb + title/description, a Dry-run toggle,
 * Run-now and Save in the header, then the module's schema fields grouped into
 * stacked section cards.
 */
const ModuleSettingsContent = ({ moduleKey }) => {
    const config = useConfig();
    const toast = useToast();
    const { schemas: dynamicSchemas } = useModuleSchema();
    // Instances config drives schema conditionals (e.g. music fields gated on a
    // configured Lidarr instance).
    const { instancesData } = useInstancesData();
    const conditionApiData = useMemo(() => ({ instances: instancesData || {} }), [instancesData]);

    const [formData, setFormData] = useState({});
    const [lastSaved, setLastSaved] = useState('{}');
    const [isSaving, setIsSaving] = useState(false);
    const [saveError, setSaveError] = useState(null);
    const [running, setRunning] = useState(false);
    // Redesign-layout disclosure state, keyed by section id: the Plex-connection
    // "Advanced" reveal and each pass's "More actions" mode reveal.
    const [openAdvanced, setOpenAdvanced] = useState({});
    const [openMoreModes, setOpenMoreModes] = useState({});

    const isDirty = useMemo(
        () => (formData && lastSaved ? JSON.stringify(formData) !== lastSaved : false),
        [formData, lastSaved]
    );
    useUnsavedChangesWarning(isDirty);

    const moduleDescriptions = useMemo(() => {
        const map = {};
        for (const m of SETTINGS_MODULES) map[m.key] = m.description;
        return map;
    }, []);

    // Initialise form data from context when config loads (render-time sync).
    const [lastConfigRef, setLastConfigRef] = useState(null);
    if (config && Object.keys(config).length > 0 && config !== lastConfigRef) {
        setLastConfigRef(config);
        setFormData(config);
        setLastSaved(JSON.stringify(config));
        setSaveError(null);
    }

    const activeModule = useMemo(
        () => dynamicSchemas.find(m => m.key === moduleKey) || null,
        [dynamicSchemas, moduleKey]
    );

    // Group the module's visible fields into section cards. `dry_run` is lifted
    // into the header, so it's excluded from the body.
    const sections = useMemo(() => {
        if (!activeModule?.fields) return [];
        const moduleData = formData[activeModule.key] || {};
        const visible = activeModule.fields.filter(
            f => f.key !== 'dry_run' && shouldShowField(f, moduleData, conditionApiData)
        );
        const groups = [];
        const idx = new Map();
        for (const f of visible) {
            const name = f.section || '';
            if (!idx.has(name)) {
                idx.set(name, groups.length);
                groups.push({ name, fields: [] });
            }
            groups[idx.get(name)].fields.push(f);
        }
        return groups;
    }, [activeModule, formData, conditionApiData]);

    // Redesign layout descriptors (opt-in): a module may declare `sections`
    // (id -> title/column/kind/modeField/enableField/...) and `columns` (the
    // two lanes + eyebrows). When absent the original single-column layout is used.
    const layout = activeModule?.sections || null;
    const columnDefs = activeModule?.columns || [];

    const hasDryRun = !!activeModule?.fields?.some(f => f.key === 'dry_run');
    const dryRunValue = !!formData[activeModule?.key]?.dry_run;
    // Config-only modules (e.g. CL2K Maker) opt out of execution via
    // `runnable: false` in their schema — no Run-now button, no Dry-run toggle,
    // and they're excluded from the Schedule. Default (undefined) stays runnable.
    const isRunnable = activeModule?.runnable !== false;

    // Unmet config preconditions a module declares via `requires` in its schema
    // (e.g. the Poster Healer needs a TMDB API key on the General page). Each
    // entry is { field: 'tmdb.apikey', message, linkTo?, linkText? }; the dotted
    // path is read from the loaded config and a falsy value means unmet. A *set*
    // secret comes back redacted as '********' (truthy), so this only fires when
    // the field is genuinely blank.
    const unmetRequirements = useMemo(() => {
        const reqs = activeModule?.requires || [];
        const read = path => path.split('.').reduce((o, k) => (o == null ? o : o[k]), formData);
        return reqs.filter(r => !read(r.field));
    }, [activeModule, formData]);

    const handleSave = useCallback(async () => {
        if (!isDirty || isSaving) return;
        try {
            setIsSaving(true);
            setSaveError(null);
            await configAPI.updateConfig(formData);
            setLastSaved(JSON.stringify(formData));
            toast.success('Saved');
        } catch (error) {
            console.error('Save failed:', error);
            setSaveError(error.message || 'Failed to save configuration');
        } finally {
            setIsSaving(false);
        }
    }, [isDirty, isSaving, formData, toast]);

    const handleReset = useCallback(() => {
        setFormData(JSON.parse(lastSaved));
        setSaveError(null);
    }, [lastSaved]);

    const handleFieldChange = useCallback((modKey, fieldKey, value) => {
        setFormData(prev => ({
            ...prev,
            [modKey]: { ...prev[modKey], [fieldKey]: value },
        }));
        setSaveError(null);
    }, []);

    const runNow = useCallback(async () => {
        if (!activeModule || running) return;
        setRunning(true);
        try {
            const res = await modulesAPI.runModule(activeModule.key);
            if (res?.data?.disabled || res?.disabled) {
                toast.error('Module is disabled — enable it on the Modules page first');
            } else {
                toast.success(`${activeModule.label} queued`);
            }
        } catch {
            toast.error('Failed to run module');
        } finally {
            setRunning(false);
        }
    }, [activeModule, running, toast]);

    // Ctrl/Cmd+S to save.
    useEffect(() => {
        const onKey = e => {
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                if (isDirty && !isSaving) handleSave();
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [isDirty, isSaving, handleSave]);

    const renderField = (field, fieldIndex) => {
        try {
            const uniqueId = `field-${activeModule.key}-${field.key}-${fieldIndex}`;
            const moduleData = formData[activeModule.key] || {};
            let fieldValue = moduleData[field.key];
            if (fieldValue === undefined) fieldValue = field.defaultValue;
            if (fieldValue === null) fieldValue = '';
            if (fieldValue && typeof fieldValue === 'object' && field.type === 'json') {
                fieldValue = JSON.stringify(fieldValue, null, 2);
            }
            return (
                <MemoizedFieldComponent
                    key={uniqueId}
                    field={{
                        ...field,
                        id: uniqueId,
                        errorId: `${uniqueId}-error`,
                        descId: `${uniqueId}-desc`,
                        ...(field.type === 'password'
                            ? { secretPath: `${activeModule.key}.${field.key}` }
                            : {}),
                    }}
                    value={fieldValue}
                    onChange={value => handleFieldChange(activeModule.key, field.key, value)}
                    disabled={isSaving}
                    highlightInvalid={false}
                    errorMessage={null}
                    rootConfig={formData}
                />
            );
        } catch (error) {
            return (
                <div
                    key={`error-${field.key}-${fieldIndex}`}
                    className="p-2 bg-warning-bg text-warning rounded"
                >
                    Field type &apos;{field.type}&apos; error: {error.message}
                </div>
            );
        }
    };

    // Normalise a segmented field's options (strings or {value,label,danger}).
    const segOptions = f =>
        (f.options || []).map(o =>
            typeof o === 'string'
                ? { value: o, label: o }
                : { value: o.value, label: o.label || o.value, danger: o.danger }
        );

    // A pass card's mode field, rendered as the full-width "Action" row. Options
    // past `meta.modeCollapseAfter` hide behind a "More actions" reveal (which
    // auto-opens when the current value is one of the collapsed options).
    const renderActionRow = (meta, modeF, moduleData) => {
        const opts = segOptions(modeF);
        const after = meta.modeCollapseAfter;
        const primary = after ? opts.slice(0, after) : opts;
        const more = after ? opts.slice(after) : [];
        const current = moduleData[modeF.key] || '';
        const moreShown = !!openMoreModes[meta.id] || more.some(o => o.value === current);
        const onPick = v => handleFieldChange(activeModule.key, modeF.key, v);
        return (
            <div>
                <div className="flex items-center gap-1 mb-2">
                    <span className="text-[14px] font-medium text-fg">
                        {meta.actionLabel || 'Action'}
                    </span>
                    {modeF.helpText && <InfoTooltip text={modeF.helpText} />}
                </div>
                <SegmentedControl fullWidth options={primary} value={current} onChange={onPick} />
                {more.length > 0 &&
                    (moreShown ? (
                        <div className="mt-2">
                            <SegmentedControl
                                fullWidth
                                options={more}
                                value={current}
                                onChange={onPick}
                            />
                        </div>
                    ) : (
                        <button
                            type="button"
                            onClick={() => setOpenMoreModes(s => ({ ...s, [meta.id]: true }))}
                            className="mt-2 inline-flex items-center gap-1 text-[12.5px] text-fg-subtle hover:text-fg"
                        >
                            <span className="material-symbols-outlined text-[16px]">
                                expand_more
                            </span>
                            More actions
                        </button>
                    ))}
                {modeF.description && (
                    <div className="text-[12px] text-fg-subtle mt-2 leading-relaxed">
                        {modeF.description}
                    </div>
                )}
            </div>
        );
    };

    // One redesign card. `kind:'pass'` sections lead with the Action row and an
    // optional header enable-toggle (dimming the body when off); `advanced`
    // fields collapse behind a disclosure; `meta.note` renders an info callout.
    const renderLayoutCard = (group, meta) => {
        const moduleData = formData[activeModule.key] || {};
        const enableF = meta.enableField
            ? group.fields.find(f => f.key === meta.enableField)
            : null;
        const modeF = meta.modeField ? group.fields.find(f => f.key === meta.modeField) : null;
        const advancedFields = group.fields.filter(f => f.advanced);
        const bodyFields = group.fields.filter(f => f !== enableF && f !== modeF && !f.advanced);
        const enabled = enableF ? !!moduleData[enableF.key] : true;
        const dimCls = enableF && !enabled ? 'opacity-50 pointer-events-none' : '';
        const subtitle = meta.subtitle || enableF?.description || '';
        return (
            <section
                key={meta.id}
                className="bg-surface border border-border rounded-xl p-5"
                style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
            >
                <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-1.5 min-w-0">
                        <h2 className="font-display text-[15px] font-semibold text-fg">
                            {meta.title}
                        </h2>
                        {enableF?.helpText && <InfoTooltip text={enableF.helpText} />}
                    </div>
                    {enableF && (
                        <Toggle
                            label={enableF.label}
                            checked={enabled}
                            onChange={v => handleFieldChange(activeModule.key, enableF.key, v)}
                        />
                    )}
                </div>
                {subtitle && (
                    <p className="text-[12.5px] text-fg-subtle mt-1 mb-0 leading-snug">
                        {subtitle}
                    </p>
                )}
                <div className={`flex flex-col gap-4 mt-4 ${dimCls}`}>
                    {modeF && renderActionRow(meta, modeF, moduleData)}
                    {bodyFields.map((field, fi) => renderField(field, fi))}
                    {advancedFields.length > 0 && (
                        <div>
                            <button
                                type="button"
                                onClick={() =>
                                    setOpenAdvanced(s => ({ ...s, [meta.id]: !s[meta.id] }))
                                }
                                className="flex items-center justify-between w-full h-[42px] px-3 rounded-[10px] bg-surface-inset border border-border text-fg-muted text-[13px] font-medium hover:text-fg transition-colors"
                            >
                                <span className="flex items-center gap-2">
                                    <span className="material-symbols-outlined text-[17px] text-fg-subtle">
                                        tune
                                    </span>
                                    Advanced connection options
                                </span>
                                <span
                                    className={`material-symbols-outlined text-[20px] text-fg-subtle transition-transform ${
                                        openAdvanced[meta.id] ? 'rotate-180' : ''
                                    }`}
                                >
                                    expand_more
                                </span>
                            </button>
                            {openAdvanced[meta.id] && (
                                <div className="flex flex-col gap-4 pt-4">
                                    {advancedFields.map((field, fi) => renderField(field, fi))}
                                </div>
                            )}
                        </div>
                    )}
                    {meta.note && (
                        <div className="flex items-start gap-2.5 p-3 rounded-[10px] bg-surface-inset border border-border-light">
                            <span className="material-symbols-outlined text-[17px] text-accent shrink-0">
                                info
                            </span>
                            <span className="text-[12px] text-fg-data leading-relaxed">
                                {meta.note}
                            </span>
                        </div>
                    )}
                </div>
            </section>
        );
    };

    return (
        <div className="flex flex-col gap-5">
            {/* Header */}
            <div className="flex flex-col gap-2.5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="min-w-0">
                        <h1 className="font-display text-[25px] font-bold tracking-[-0.3px] text-fg m-0">
                            {activeModule ? activeModule.label : 'Module'}
                        </h1>
                        {activeModule && moduleDescriptions[activeModule.key] && (
                            <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">
                                {moduleDescriptions[activeModule.key]}
                            </p>
                        )}
                    </div>
                    {activeModule && (
                        <div className="flex flex-wrap items-center gap-2.5 shrink-0 max-w-full">
                            {hasDryRun && isRunnable && (
                                <label className="flex items-center gap-2 text-[13px] text-fg-muted cursor-pointer select-none">
                                    Dry run
                                    <Toggle
                                        label="Dry run"
                                        checked={dryRunValue}
                                        onChange={v =>
                                            handleFieldChange(activeModule.key, 'dry_run', v)
                                        }
                                    />
                                </label>
                            )}
                            {isRunnable && (
                                <button
                                    type="button"
                                    onClick={runNow}
                                    disabled={running}
                                    className="inline-flex items-center gap-1.5 h-[38px] px-3.5 rounded-lg bg-surface border border-border text-fg-muted text-[13.5px] font-medium hover:bg-row-hover disabled:opacity-50 transition-colors"
                                >
                                    <span className="material-symbols-outlined text-[18px]">
                                        play_arrow
                                    </span>
                                    {running ? 'Queuing…' : 'Run now'}
                                </button>
                            )}
                            {isDirty && (
                                <button
                                    type="button"
                                    onClick={handleReset}
                                    className="h-[38px] px-3 rounded-lg text-[13px] text-fg-subtle hover:text-fg"
                                >
                                    Discard
                                </button>
                            )}
                            <button
                                type="button"
                                onClick={handleSave}
                                disabled={!isDirty || isSaving}
                                className="inline-flex items-center h-[38px] px-[18px] rounded-lg bg-primary text-on-color font-display text-[13.5px] font-semibold hover:brightness-110 disabled:opacity-50 transition"
                                style={{ boxShadow: '0 4px 16px -5px var(--primary)' }}
                            >
                                {isSaving ? 'Saving…' : 'Save'}
                            </button>
                        </div>
                    )}
                </div>
            </div>

            {saveError && (
                <div className="p-3 bg-error-bg border border-error-border text-error rounded-lg max-w-[820px]">
                    <div className="flex items-center gap-2">
                        <span className="material-symbols-outlined text-sm">error</span>
                        {saveError}
                    </div>
                </div>
            )}

            {unmetRequirements.map((req, i) => (
                <div
                    key={`req-${i}`}
                    className="p-3 bg-warning-bg border border-warning text-warning rounded-lg max-w-[820px]"
                >
                    <div className="flex items-center gap-2">
                        <span className="material-symbols-outlined text-sm">warning</span>
                        <span>
                            {req.message}
                            {req.linkTo && (
                                <>
                                    {' '}
                                    <Link
                                        to={req.linkTo}
                                        className="underline font-medium hover:opacity-80"
                                    >
                                        {req.linkText || 'Open settings'}
                                    </Link>
                                </>
                            )}
                        </span>
                    </div>
                </div>
            ))}

            {!activeModule ? (
                <div className="text-center py-12 text-fg-subtle">
                    <span className="material-symbols-outlined text-4xl mb-2 block">
                        help_outline
                    </span>
                    <p>Unknown module.</p>
                    <Link to="/settings/modules" className="text-accent hover:underline">
                        Back to Modules
                    </Link>
                </div>
            ) : layout ? (
                <div className="w-full max-w-[1180px] flex flex-wrap gap-5 items-start">
                    {sections.length === 0 ? (
                        <div className="w-full text-center py-10 text-fg-subtle rounded-xl border border-dashed border-border">
                            <span className="material-symbols-outlined text-3xl mb-2 block">
                                inbox
                            </span>
                            <p>This module has no configurable options.</p>
                        </div>
                    ) : (
                        <>
                            {columnDefs.map(col => (
                                <div
                                    key={col.id}
                                    className="flex-1 flex flex-col gap-5"
                                    style={{ minWidth: 'min(430px, 100%)' }}
                                >
                                    <div className="flex items-center gap-2.5 px-0.5 pb-0.5">
                                        <span className="material-symbols-outlined text-[17px] text-primary">
                                            {col.icon}
                                        </span>
                                        <span className="font-mono text-[11px] tracking-[0.12em] uppercase text-fg-faint">
                                            {col.label}
                                        </span>
                                        <div className="flex-1 h-px bg-border-light" />
                                    </div>
                                    {layout
                                        .filter(m => m.column === col.id)
                                        .map(meta => {
                                            const group = sections.find(g => g.name === meta.id);
                                            return group ? renderLayoutCard(group, meta) : null;
                                        })}
                                </div>
                            ))}
                            {/* Safety net: any visible section NOT claimed by a column
                                (a `sections` entry missing/typo'd, an unknown column, or
                                a backend-injected field) still renders full-width below,
                                so the two-column layout can never silently drop a
                                configured option. */}
                            {(() => {
                                const cols = new Set(columnDefs.map(c => c.id));
                                const claimed = new Set(
                                    layout.filter(m => cols.has(m.column)).map(m => m.id)
                                );
                                const orphans = sections.filter(g => !claimed.has(g.name));
                                if (orphans.length === 0) return null;
                                return (
                                    <div className="w-full flex flex-col gap-5">
                                        {orphans.map(group =>
                                            renderLayoutCard(group, {
                                                id: group.name || 'other',
                                                title: group.name || 'Other options',
                                                kind: 'form',
                                            })
                                        )}
                                    </div>
                                );
                            })()}
                        </>
                    )}
                </div>
            ) : (
                <div className="w-full max-w-[820px] flex flex-col gap-4">
                    {sections.length === 0 ? (
                        <div className="text-center py-10 text-fg-subtle rounded-xl border border-dashed border-border">
                            <span className="material-symbols-outlined text-3xl mb-2 block">
                                inbox
                            </span>
                            <p>This module has no configurable options.</p>
                        </div>
                    ) : (
                        sections.map((group, gi) => {
                            // A section may hoist two fields into its header: a
                            // `sectionToggle` enable switch (rendered as a Toggle
                            // beside the title) and a `placement: 'header'` control
                            // (e.g. a report/move/remove mode segmented, right-
                            // aligned). When the enable toggle is off, the header
                            // control + body are dimmed. Sections without these
                            // flags render exactly as before.
                            const moduleData = formData[activeModule.key] || {};
                            const enableF = group.fields.find(f => f.sectionToggle);
                            const headerF = group.fields.find(f => f.placement === 'header');
                            const bodyFields = group.fields.filter(
                                f => f !== enableF && f !== headerF
                            );
                            const enabled = enableF ? !!moduleData[enableF.key] : true;
                            const dimCls =
                                enableF && !enabled ? 'opacity-50 pointer-events-none' : '';
                            return (
                                <section
                                    key={group.name || `section-${gi}`}
                                    className="bg-surface border border-border rounded-xl p-5"
                                    style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
                                >
                                    {(group.name || enableF || headerF) && (
                                        <div className="flex items-center justify-between gap-3 mb-4">
                                            <div className="flex items-center gap-2.5 min-w-0">
                                                {group.name && (
                                                    <h2 className="font-display text-[15px] font-semibold text-fg">
                                                        {group.name}
                                                    </h2>
                                                )}
                                                {enableF && (
                                                    <Toggle
                                                        label={enableF.label}
                                                        checked={enabled}
                                                        onChange={v =>
                                                            handleFieldChange(
                                                                activeModule.key,
                                                                enableF.key,
                                                                v
                                                            )
                                                        }
                                                    />
                                                )}
                                            </div>
                                            {headerF && (
                                                <div className={dimCls}>
                                                    <SegmentedControl
                                                        size="sm"
                                                        options={segOptions(headerF)}
                                                        value={moduleData[headerF.key] || ''}
                                                        onChange={v =>
                                                            handleFieldChange(
                                                                activeModule.key,
                                                                headerF.key,
                                                                v
                                                            )
                                                        }
                                                    />
                                                </div>
                                            )}
                                        </div>
                                    )}
                                    {/* A sectionToggle/header-mode field is hoisted into the
                                        header above, which drops its description. Surface it
                                        here so enable-only sections (e.g. Stale duplicates) read
                                        as more than a bare toggle. Kept full-opacity — it
                                        explains what enabling the section does. */}
                                    {enableF?.description && (
                                        <p className="text-sm text-fg-subtle -mt-2 mb-4">
                                            {enableF.description}
                                        </p>
                                    )}
                                    <div className={`flex flex-col gap-4 ${dimCls}`}>
                                        {bodyFields.map((field, fi) => renderField(field, fi))}
                                    </div>
                                </section>
                            );
                        })
                    )}
                </div>
            )}
        </div>
    );
};

export const ModuleSettingsPage = () => {
    const { moduleKey } = useParams();
    const [config, setConfig] = useState({});
    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        const loadConfig = async () => {
            try {
                setIsLoading(true);
                const response = await configAPI.fetchConfig();
                setConfig(response?.data || {});
            } catch (error) {
                console.error('Failed to load config:', error);
                setConfig({});
            } finally {
                setIsLoading(false);
            }
        };
        loadConfig();
    }, []);

    if (isLoading) {
        return (
            <div className="p-6 max-w-4xl mx-auto">
                <div className="flex items-center justify-center py-12">
                    <div className="text-center">
                        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto mb-4"></div>
                        <p className="text-fg-muted">Loading configuration...</p>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <ConfigProvider config={config}>
            <ModuleSettingsContent moduleKey={moduleKey} />
        </ConfigProvider>
    );
};

export default ModuleSettingsPage;
