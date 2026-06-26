import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
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

    const hasDryRun = !!activeModule?.fields?.some(f => f.key === 'dry_run');
    const dryRunValue = !!formData[activeModule?.key]?.dry_run;

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

    return (
        <div className="flex flex-col gap-5">
            {/* Breadcrumb + header */}
            <div className="flex flex-col gap-2.5">
                <nav className="font-mono text-[11.5px] text-fg-subtle">
                    <Link to="/settings/modules" className="hover:text-fg">
                        Modules
                    </Link>{' '}
                    / <span className="text-fg-muted">{activeModule?.label || moduleKey}</span>
                </nav>
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
                        <div className="flex items-center gap-2.5 shrink-0">
                            {hasDryRun && (
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
                        sections.map((group, gi) => (
                            <section
                                key={group.name || `section-${gi}`}
                                className="bg-surface border border-border rounded-xl p-5"
                                style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
                            >
                                {group.name && (
                                    <h2 className="font-display text-[15px] font-semibold text-fg mb-4">
                                        {group.name}
                                    </h2>
                                )}
                                <div className="flex flex-col gap-4">
                                    {group.fields.map((field, fi) => renderField(field, fi))}
                                </div>
                            </section>
                        ))
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
