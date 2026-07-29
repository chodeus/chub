/**
 * GeneralSettingsPage Component
 *
 * Page for managing general CHUB settings like logging and notifications.
 * Uses the same form architecture as ModuleSettingsPage but for general configuration.
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router';
import { GENERAL_SETTINGS_SCHEMA } from '../../utils/constants/general_settings_schema.js';
import { FieldRegistry } from '../../components/fields/FieldRegistry.jsx';
import { PageHeader } from '../../components/ui/PageHeader';
import { ToolBar } from '../../components/ToolBar';
import { useApiData } from '../../hooks/useApiData';
import { configAPI } from '../../utils/api/config';
import { useToast } from '../../contexts/ToastContext';
import { useTheme } from '../../contexts/ThemeContext';
import { useToolbar } from '../../contexts/ToolbarContext';
import { useUnsavedChangesWarning } from '../../hooks/useUnsavedChangesWarning';

/**
 * Memoized field component for better performance
 * Only re-renders when field value or key changes
 */
const MemoizedFieldComponent = React.memo(
    ({ field, value, onChange, ...props }) => {
        // Stable module-level component reference; use createElement to avoid
        // react-hooks/component-hooks-in-render false positive.
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
    (prevProps, nextProps) => {
        return (
            prevProps.value === nextProps.value &&
            prevProps.field.key === nextProps.field.key &&
            prevProps.disabled === nextProps.disabled &&
            prevProps.highlightInvalid === nextProps.highlightInvalid
        );
    }
);

MemoizedFieldComponent.displayName = 'MemoizedFieldComponent';

const normalizeDuplicateExcludeGroups = groups => {
    if (!Array.isArray(groups)) return [];
    return groups
        .map(group => {
            if (Array.isArray(group)) {
                return { instances: group };
            }
            return group && typeof group === 'object' ? group : null;
        })
        .filter(Boolean);
};

/**
 * GeneralSettingsPage component for managing general CHUB configuration
 * @returns {JSX.Element} General settings page component
 */
export const GeneralSettingsPage = () => {
    const toast = useToast();
    const { setTheme, accent, setAccent, accents } = useTheme();
    const { registerToolbar, clearToolbar } = useToolbar();

    // Load config from backend
    const {
        data: configData,
        isLoading,
        error: loadError,
        execute: refreshConfig,
    } = useApiData({
        apiFunction: configAPI.fetchConfig,
    });

    const navigate = useNavigate();
    const [formData, setFormData] = useState({});
    const [lastSaved, setLastSaved] = useState('{}');
    const [isSaving, setIsSaving] = useState(false);
    const [saveError, setSaveError] = useState(null);

    // Initialize form data when backend config loads. Render-time setState
    // (React docs "adjusting state when a prop changes") avoids a
    // setState-in-effect bootstrap.
    const [lastConfigData, setLastConfigData] = useState(null);
    if (configData?.data && configData !== lastConfigData) {
        setLastConfigData(configData);
        const generalData = configData.data.general || {
            log_level: 'info',
            max_logs: 9,
            webhook_initial_delay: 30,
            webhook_retry_delay: 30,
            webhook_max_retries: 10,
            webhook_secret: '',
            duplicate_exclude_groups: [],
        };
        const initialData = {
            user_interface: configData.data.user_interface || { theme: 'auto' },
            // tmdb + fanart surface their API keys on this page (see
            // general_settings_schema). Load them so the fields show current
            // state (the redacted placeholder when a key is set) and the save
            // round-trips the section intact.
            tmdb: configData.data.tmdb || {},
            fanart: configData.data.fanart || {},
            general: {
                ...generalData,
                duplicate_exclude_groups: normalizeDuplicateExcludeGroups(
                    generalData.duplicate_exclude_groups
                ),
            },
        };
        setFormData(initialData);
        setLastSaved(JSON.stringify(initialData));
        setSaveError(null);
    }

    // Sync theme to ThemeContext whenever the loaded config's theme changes
    // (e.g. another tab saved a different value). setTheme is an external
    // store update, so it's allowed inside an effect.
    useEffect(() => {
        const configTheme = configData?.data?.user_interface?.theme;
        if (configTheme) {
            setTheme(configTheme === 'auto' ? 'system' : configTheme);
        }
    }, [configData, setTheme]);

    // Dirty flag is derived from formData vs. lastSaved — no state or effect needed.
    const isDirty = useMemo(
        () => (formData && lastSaved ? JSON.stringify(formData) !== lastSaved : false),
        [formData, lastSaved]
    );
    useUnsavedChangesWarning(isDirty);

    // Handle field changes
    const handleFieldChange = useCallback(
        (moduleKey, fieldKey, value) => {
            setFormData(prev => ({
                ...prev,
                [moduleKey]: {
                    ...prev[moduleKey],
                    [fieldKey]: value,
                },
            }));
            setSaveError(null);

            // Live-preview theme switches so the user sees the swap before
            // hitting Save. The persisted value is the actual config field
            // (saved in handleSave); ThemeContext maps "auto" → "system".
            if (moduleKey === 'user_interface' && fieldKey === 'theme') {
                setTheme(value === 'auto' ? 'system' : value);
            }
        },
        [setTheme]
    );

    // Save configuration
    const handleSave = useCallback(async () => {
        if (!isDirty || isSaving) return;

        try {
            setIsSaving(true);
            setSaveError(null);

            // Save to backend
            await configAPI.updateConfig(formData);

            // Refresh config with cache bypass
            await refreshConfig({ useCache: false });

            // Update tracking after successful save. isDirty auto-clears once
            // lastSaved matches formData.
            setLastSaved(JSON.stringify(formData));

            toast.success('General settings saved successfully');
        } catch (error) {
            console.error('Save failed:', error);
            const errorMessage = error.message || 'Failed to save configuration';
            setSaveError(errorMessage);
            toast.error(`Failed to save settings: ${errorMessage}`);
        } finally {
            setIsSaving(false);
        }
    }, [isDirty, isSaving, formData, refreshConfig, toast]);

    // Reset to last saved state — isDirty auto-clears via derivation.
    const handleReset = useCallback(() => {
        const restored = JSON.parse(lastSaved);
        setFormData(restored);
        setSaveError(null);
        const restoredTheme = restored.user_interface?.theme;
        if (restoredTheme) {
            setTheme(restoredTheme === 'auto' ? 'system' : restoredTheme);
        }
    }, [lastSaved, setTheme]);

    // Register toolbar with Save/Reset buttons
    useEffect(() => {
        const toolbarContent = (
            <ToolBar>
                <ToolBar.Section alignContent="right">
                    <ToolBar.Button
                        label="Cancel Changes"
                        iconName="restore"
                        isDisabled={!isDirty || isSaving}
                        onPress={handleReset}
                    />
                    <ToolBar.Button
                        label="Save"
                        iconName="save"
                        variant="primary"
                        isDisabled={!isDirty || isSaving}
                        isSpinning={isSaving}
                        onPress={handleSave}
                    />
                </ToolBar.Section>
            </ToolBar>
        );

        registerToolbar(toolbarContent);

        // Cleanup on unmount
        return () => clearToolbar();
    }, [isDirty, isSaving, handleSave, handleReset, registerToolbar, clearToolbar]);

    // Keyboard shortcuts
    useEffect(() => {
        const handleKeyboard = e => {
            // Ctrl/Cmd + S to save
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                if (isDirty && !isSaving) {
                    handleSave();
                }
            }

            // Ctrl/Cmd+R is intentionally not intercepted — that's the
            // browser reload shortcut. Reset stays available via the Reset
            // button in the toolbar.
        };

        window.addEventListener('keydown', handleKeyboard);
        return () => window.removeEventListener('keydown', handleKeyboard);
    }, [isDirty, isSaving, handleSave, handleReset]);

    // Loading state
    if (isLoading) {
        return (
            <div className="flex justify-center items-center min-h-64">
                <div className="text-fg text-lg">Loading general settings...</div>
            </div>
        );
    }

    // Error state
    if (loadError) {
        return (
            <div className="flex justify-center items-center min-h-64">
                <div className="text-error text-lg">
                    Error loading settings: {loadError.message}
                </div>
            </div>
        );
    }

    return (
        <div className="max-w-4xl mx-auto flex flex-col gap-4">
            {/* Header */}
            <PageHeader title="General" description="Appearance, dashboard, and access." />

            {/* Error display */}
            {saveError && (
                <div className="p-3 bg-error-bg border border-error-border text-error rounded-lg">
                    <div className="flex items-center gap-2">
                        <span className="material-symbols-outlined text-sm">error</span>
                        {saveError}
                    </div>
                </div>
            )}

            {/* Appearance — theme + accent (mock's Appearance section). Replaces
                the schema's plain theme dropdown (filtered out of the map below). */}
            <div className="bg-surface border border-border rounded-xl p-5">
                <h2 className="font-display text-[15px] font-semibold mb-4 text-fg">Appearance</h2>
                <div className="flex flex-col gap-4">
                    <div className="flex items-center justify-between gap-4 flex-wrap">
                        <div>
                            <div className="text-sm font-medium text-fg">Theme</div>
                            <div className="text-xs text-fg-subtle mt-0.5">
                                Light, dark, or follow system
                            </div>
                        </div>
                        <div className="flex gap-1 p-1 rounded-lg bg-surface-inset border border-border">
                            {[
                                ['light', 'Light'],
                                ['dark', 'Dark'],
                                ['auto', 'System'],
                            ].map(([val, label]) => {
                                const active = (formData.user_interface?.theme || 'auto') === val;
                                return (
                                    <button
                                        key={val}
                                        type="button"
                                        onClick={() =>
                                            handleFieldChange('user_interface', 'theme', val)
                                        }
                                        className={`px-3.5 py-1.5 rounded-md text-[13px] transition-colors ${
                                            active
                                                ? 'bg-primary text-on-color font-semibold'
                                                : 'text-fg-muted hover:text-fg'
                                        }`}
                                    >
                                        {label}
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                    <div className="flex items-center justify-between gap-4 flex-wrap border-t border-border-light pt-4">
                        <div>
                            <div className="text-sm font-medium text-fg">Accent</div>
                            <div className="text-xs text-fg-subtle mt-0.5">
                                Recolours buttons, nav, toggles and links
                            </div>
                        </div>
                        <div className="flex items-center gap-2.5">
                            {Object.entries(accents).map(([key, a]) => {
                                const active = accent === key;
                                return (
                                    <button
                                        key={key}
                                        type="button"
                                        onClick={() => setAccent(key)}
                                        aria-label={a.label}
                                        aria-pressed={active}
                                        title={a.label}
                                        className="w-8 h-8 touch-expand rounded-lg transition-transform hover:scale-105"
                                        style={{
                                            background: a.brand,
                                            boxShadow: active
                                                ? `0 0 0 2px var(--surface), 0 0 0 4px ${a.brand}`
                                                : undefined,
                                        }}
                                    />
                                );
                            })}
                        </div>
                    </div>
                </div>
            </div>

            {/* Settings card */}
            {GENERAL_SETTINGS_SCHEMA.filter(module => module.key !== 'user_interface').map(
                (module, moduleIndex) => (
                    <div
                        key={`module-${module.key}-${moduleIndex}`}
                        className="bg-surface border border-border rounded-xl p-5"
                    >
                        <h2 className="font-display text-[15px] font-semibold mb-4 text-fg">
                            {module.label}
                        </h2>

                        {module.fields && module.fields.length > 0 ? (
                            <form
                                onSubmit={e => {
                                    e.preventDefault();
                                    handleSave();
                                }}
                                className="space-y-4 md:space-y-6"
                                noValidate
                            >
                                {module.fields.map((field, fieldIndex) => {
                                    try {
                                        // Generate unique IDs for this field instance
                                        const uniqueId = `field-${module.key}-${field.key}-${fieldIndex}`;
                                        const errorId = `${uniqueId}-error`;
                                        const descId = `${uniqueId}-desc`;

                                        // Get field value from current module data
                                        const moduleData = formData[module.key] || {};
                                        let fieldValue = moduleData[field.key];

                                        // Handle special case for nested values
                                        if (fieldValue === undefined) {
                                            fieldValue = field.defaultValue;
                                        }

                                        // Handle null values - convert to empty string for form fields
                                        if (fieldValue === null) {
                                            fieldValue = '';
                                        }

                                        // Handle object values - stringify for JSON fields
                                        if (
                                            fieldValue &&
                                            typeof fieldValue === 'object' &&
                                            field.type === 'json'
                                        ) {
                                            fieldValue = JSON.stringify(fieldValue, null, 2);
                                        }

                                        return (
                                            <div
                                                key={`field-${module.key}-${field.key}-${fieldIndex}`}
                                            >
                                                <MemoizedFieldComponent
                                                    field={{
                                                        ...field,
                                                        id: uniqueId,
                                                        errorId,
                                                        descId,
                                                        ...(field.type === 'password'
                                                            ? {
                                                                  secretPath: `${module.key}.${field.key}`,
                                                              }
                                                            : {}),
                                                    }}
                                                    value={fieldValue}
                                                    onChange={value =>
                                                        handleFieldChange(
                                                            module.key,
                                                            field.key,
                                                            value
                                                        )
                                                    }
                                                    disabled={isSaving}
                                                    highlightInvalid={false}
                                                    errorMessage={null}
                                                    rootConfig={formData}
                                                />
                                            </div>
                                        );
                                    } catch (error) {
                                        console.error(`Error rendering field ${field.key}:`, error);
                                        return (
                                            <div
                                                key={`error-${module.key}-${field.key}-${fieldIndex}`}
                                                className="p-2 bg-warning-bg text-warning rounded"
                                            >
                                                Field type &apos;{field.type}&apos; error:{' '}
                                                {error.message}
                                            </div>
                                        );
                                    }
                                })}
                            </form>
                        ) : (
                            <div className="text-center py-8 text-fg-subtle">
                                <span className="material-symbols-outlined text-4xl mb-2 block">
                                    inbox
                                </span>
                                <p>No general settings available</p>
                            </div>
                        )}
                    </div>
                )
            )}

            {/* First-run setup — re-runs the full-screen Setup Wizard. The
                wizard also auto-launches on a fresh install; this is the
                re-entry point now that the Settings hub page is gone. */}
            <div className="bg-surface border border-border rounded-xl p-5">
                <h2 className="font-display text-[15px] font-semibold mb-1 text-fg">
                    First-run setup
                </h2>
                <p className="text-[13px] text-fg-subtle mb-4">
                    Re-run the guided setup wizard to reconfigure instances, paths, and modules.
                </p>
                <button
                    type="button"
                    onClick={() => navigate('/setup')}
                    className="inline-flex items-center gap-2 h-9 px-4 rounded-lg bg-surface-inset border border-border text-fg-muted text-[13px] font-semibold transition-colors hover:border-border-light hover:text-fg"
                >
                    <span className="material-symbols-outlined text-base">auto_fix_high</span>
                    Launch wizard
                </button>
            </div>
        </div>
    );
};

export default GeneralSettingsPage;
