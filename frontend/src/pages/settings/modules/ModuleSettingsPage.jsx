import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { configAPI } from '../../../utils/api/config.js';
import { SETTINGS_MODULES } from '../../../utils/constants/settings_schema.js';
import { useModuleSchema } from '../../../hooks/useModuleSchema.js';
import { FieldRegistry } from '../../../components/fields/FieldRegistry.jsx';
import { Accordion } from '../../../components/ui/Accordion.jsx';
import { AccordionItem } from '../../../components/ui/AccordionItem.jsx';
import { ConfigProvider, useConfig } from '../../../contexts/ConfigContext.jsx';
import { PageHeader } from '../../../components/ui/PageHeader';
import { ToolBar } from '../../../components/ToolBar';
import { useToolbar } from '../../../contexts/ToolbarContext';

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

/**
 * Internal component that uses ConfigContext for optimal data access
 * @returns {JSX.Element} Module settings content component
 */
const ModuleSettingsContent = () => {
    const config = useConfig(); // Clean access to configuration data
    const { registerToolbar, clearToolbar } = useToolbar();
    const { schemas: dynamicSchemas } = useModuleSchema();

    // Simplified state management for the UI
    const [expandedModules, setExpandedModules] = useState([]);
    const [formData, setFormData] = useState({});
    const [lastSaved, setLastSaved] = useState('{}');
    const [isSaving, setIsSaving] = useState(false);
    const [saveError, setSaveError] = useState(null);
    const [saveSuccess, setSaveSuccess] = useState(false);

    // Dirty flag derived from formData vs. lastSaved — no state or effect needed.
    const isDirty = useMemo(
        () => (formData && lastSaved ? JSON.stringify(formData) !== lastSaved : false),
        [formData, lastSaved]
    );

    // Module description lookup
    const moduleDescriptions = useMemo(() => {
        const map = {};
        for (const m of SETTINGS_MODULES) {
            map[m.key] = m.description;
        }
        return map;
    }, []);

    // Search and filter state
    const [searchTerm, setSearchTerm] = useState('');

    // Initialize form data from context when config loads (render-time sync
    // pattern, avoids setState-in-effect).
    const [lastConfigRef, setLastConfigRef] = useState(null);
    if (config && Object.keys(config).length > 0 && config !== lastConfigRef) {
        setLastConfigRef(config);
        setFormData(config);
        setLastSaved(JSON.stringify(config));
        setSaveError(null);
    }

    // Clear success message after delay
    useEffect(() => {
        if (saveSuccess) {
            const timer = setTimeout(() => setSaveSuccess(false), 3000);
            return () => clearTimeout(timer);
        }
    }, [saveSuccess]);

    // Filtered modules derived from searchTerm + dynamicSchemas.
    const filteredModules = useMemo(() => {
        if (!searchTerm) return dynamicSchemas;
        const q = searchTerm.toLowerCase();
        return dynamicSchemas.filter(
            module =>
                module.label.toLowerCase().includes(q) ||
                module.fields?.some(
                    field =>
                        field.label?.toLowerCase().includes(q) ||
                        field.key?.toLowerCase().includes(q)
                )
        );
    }, [searchTerm, dynamicSchemas]);

    // Save configuration - simplified with Context
    const handleSave = useCallback(async () => {
        if (!isDirty || isSaving) return;

        try {
            setIsSaving(true);
            setSaveError(null);

            await configAPI.updateConfig(formData);

            // Update tracking after successful save. isDirty auto-clears via derivation.
            setLastSaved(JSON.stringify(formData));
            setSaveSuccess(true);
        } catch (error) {
            console.error('Save failed:', error);
            setSaveError(error.message || 'Failed to save configuration');
        } finally {
            setIsSaving(false);
        }
    }, [isDirty, isSaving, formData]);

    // Reset to last saved state - simplified with Context
    const handleReset = useCallback(() => {
        setFormData(config);
        setSaveError(null);
    }, [config]);

    // Handle field changes following main UI pattern
    const handleFieldChange = useCallback((moduleKey, fieldKey, value) => {
        setFormData(prev => ({
            ...prev,
            [moduleKey]: {
                ...prev[moduleKey],
                [fieldKey]: value,
            },
        }));
        setSaveError(null);
    }, []);

    // Register toolbar with Save/Reset buttons
    useEffect(() => {
        const toolbarContent = (
            <ToolBar>
                <ToolBar.Section alignContent="right">
                    <ToolBar.Button
                        label="Reset"
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

            // Ctrl/Cmd + R to reset
            if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
                e.preventDefault();
                if (isDirty) {
                    handleReset();
                }
            }

            // Escape to collapse all
            if (e.key === 'Escape') {
                setExpandedModules([]);
            }
        };

        window.addEventListener('keydown', handleKeyboard);
        return () => window.removeEventListener('keydown', handleKeyboard);
    }, [isDirty, isSaving, handleReset, handleSave]);

    const toggleModule = moduleKey => {
        setExpandedModules(prev =>
            prev.includes(moduleKey) ? prev.filter(key => key !== moduleKey) : [...prev, moduleKey]
        );
    };

    // No loading state needed - data comes from ConfigProvider

    return (
        <div className="p-4 md:p-6 max-w-4xl mx-auto">
            {/* Header */}
            <PageHeader
                title="Modules"
                description="Per-module configuration and options."
                badge={4}
                icon="extension"
            />

            {/* Error display */}
            {saveError && (
                <div className="mt-4 p-3 bg-error-bg border border-error-border text-error rounded">
                    <div className="flex items-center gap-2">
                        <span className="material-symbols-outlined text-sm">error</span>
                        {saveError}
                    </div>
                </div>
            )}

            {/* Search functionality */}
            <div className="mb-6">
                <div className="relative">
                    <span className="material-symbols-outlined absolute left-3 top-3 text-secondary">
                        search
                    </span>
                    <input
                        type="text"
                        placeholder="Search modules and fields..."
                        value={searchTerm}
                        onChange={e => setSearchTerm(e.target.value)}
                        className="w-full pl-10 pr-4 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent min-h-11 bg-surface text-primary"
                    />
                </div>
            </div>

            {/* Module accordion */}
            <Accordion>
                {filteredModules.map((module, moduleIndex) => (
                    <AccordionItem
                        key={`module-${module.key}-${moduleIndex}`}
                        isExpanded={expandedModules.includes(module.key)}
                        onToggle={() => toggleModule(module.key)}
                    >
                        <AccordionItem.Header className="px-6 py-4 bg-surface hover:bg-surface-hover border-b border-border-subtle">
                            <div className="flex items-center justify-between min-h-11">
                                <div className="flex flex-col">
                                    <span className="font-medium text-base text-primary">
                                        {module.label}
                                    </span>
                                    {moduleDescriptions[module.key] && (
                                        <span className="text-xs text-tertiary mt-0.5">
                                            {moduleDescriptions[module.key]}
                                        </span>
                                    )}
                                </div>
                                <span
                                    className="material-symbols-outlined text-xl text-secondary transition-transform duration-200"
                                    style={{
                                        transform: expandedModules.includes(module.key)
                                            ? 'rotate(90deg)'
                                            : 'rotate(0deg)',
                                    }}
                                >
                                    chevron_right
                                </span>
                            </div>
                        </AccordionItem.Header>
                        <AccordionItem.Body className="bg-surface-elevated border-t border-border-subtle p-6">
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

                                            // Get field value from current module data - CORRECTED VALUE MAPPING
                                            // formData structure is flat: sync_gdrive, poster_renamerr, etc. are direct properties
                                            const moduleData = formData[module.key] || {};
                                            let fieldValue = moduleData[field.key];

                                            // DEBUG: Detailed logging for sync_gdrive
                                            if (
                                                module.key === 'sync_gdrive' &&
                                                field.key === 'log_level'
                                            ) {
                                                // Debug removed
                                            }

                                            // Handle special case for nested values (like token)
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
                                                    className="settings-field-row"
                                                >
                                                    <MemoizedFieldComponent
                                                        field={{
                                                            ...field,
                                                            id: uniqueId,
                                                            errorId,
                                                            descId,
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
                                            console.error(
                                                `Error rendering field ${field.key}:`,
                                                error
                                            );
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
                                <div className="text-center py-8 text-tertiary">
                                    <span className="material-symbols-outlined text-4xl mb-2 block">
                                        inbox
                                    </span>
                                    <p>This module&apos;s configuration is still being developed</p>
                                </div>
                            )}
                        </AccordionItem.Body>
                    </AccordionItem>
                ))}
            </Accordion>
        </div>
    );
};

/**
 * Main module settings page with optimal ConfigProvider architecture
 * This provides clean separation of concerns:
 * - ConfigProvider handles API data loading
 * - ModuleSettingsContent handles UI state and form interaction
 * @returns {JSX.Element} Module settings page component
 */
export const ModuleSettingsPage = () => {
    const [config, setConfig] = useState({});
    const [isLoading, setIsLoading] = useState(true);

    // Load configuration data
    useEffect(() => {
        const loadConfig = async () => {
            try {
                setIsLoading(true);
                const response = await configAPI.fetchConfig();
                // Extract the actual config data from the API response
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
                        <p className="text-secondary">Loading configuration...</p>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <ConfigProvider config={config}>
            <ModuleSettingsContent />
        </ConfigProvider>
    );
};

export default ModuleSettingsPage;
