import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { PageHeader } from '../../components/ui/PageHeader';
import { StatGrid } from '../../components/statistics';
import { StatCard } from '../../components/ui';
import { InstanceCard } from '../../components/instances/InstanceCard';
import { Button } from '../../components/ui/button/Button';
import { Modal } from '../../components/ui';
import { FieldRegistry } from '../../components/fields/FieldRegistry';
import { ServiceIcon } from '../../components/ui/ServiceIcon';
import { useApiData } from '../../hooks/useApiData';
import { useToast } from '../../contexts/ToastContext';
import { instancesAPI } from '../../utils/api/instances';
import { configAPI } from '../../utils/api/config';
import { INSTANCE_SCHEMA } from '../../utils/constants/instance_schema';
import { humanize } from '../../utils/tools';

// Friendly presets for the background media-cache reconciliation cadence
// (config.instances.sync_schedule). Cron form so the scheduler's per-name
// next-run guard prevents double-firing.
const SYNC_PRESETS = [
    { key: 'off', label: 'Off', value: '' },
    { key: '6h', label: 'Every 6 hours', value: 'cron(0 */6 * * *)' },
    { key: 'daily', label: 'Daily', value: 'cron(0 4 * * *)' },
    { key: 'weekly', label: 'Weekly', value: 'cron(0 4 * * 0)' },
];

/**
 * Instances Management page
 */
export const InstancesPage = () => {
    // Data loading
    const {
        data: instances,
        isLoading,
        error,
        execute: refreshInstances,
    } = useApiData({
        apiFunction: instancesAPI.fetchInstances,
    });

    // Toast notifications
    const toast = useToast();

    // Connection testing state
    const [testingInstances, setTestingInstances] = useState(new Set());
    const [connectionStatus, setConnectionStatus] = useState({});

    // Syncing state
    const [syncingInstances, setSyncingInstances] = useState(new Set());

    // Auto-sync cadence (config.instances.sync_schedule). A small, secondary
    // control — the cron strings are mapped to a few friendly presets.
    const [syncSchedule, setSyncSchedule] = useState('');
    const [syncScheduleLoaded, setSyncScheduleLoaded] = useState(false);
    const [syncScheduleSaving, setSyncScheduleSaving] = useState(false);

    useEffect(() => {
        let cancelled = false;
        configAPI
            .fetchSection('instances')
            .then(resp => {
                // A sectioned GET nests under the section name
                // (data.instances.*); tolerate a flat shape too.
                const inst = resp?.data?.instances ?? resp?.data ?? {};
                if (!cancelled) setSyncSchedule(inst.sync_schedule ?? '');
            })
            .catch(() => {})
            .finally(() => {
                if (!cancelled) setSyncScheduleLoaded(true);
            });
        return () => {
            cancelled = true;
        };
    }, []);

    const handleSyncPresetChange = useCallback(
        async value => {
            const prev = syncSchedule;
            setSyncSchedule(value);
            setSyncScheduleSaving(true);
            try {
                // Send only this field; the backend merge preserves the instance
                // entries (and their redacted keys) under `instances`.
                await configAPI.updateConfig({ instances: { sync_schedule: value } });
                toast.success('Auto-sync schedule updated');
            } catch (err) {
                setSyncSchedule(prev);
                toast.error(`Couldn't update auto-sync: ${err.message}`);
            } finally {
                setSyncScheduleSaving(false);
            }
        },
        [syncSchedule, toast]
    );

    // Health, stats, logs, and libraries state
    const [healthData, setHealthData] = useState({});
    const [statsData, setStatsData] = useState({});
    const [logsData, setLogsData] = useState({});
    const [librariesData, setLibrariesData] = useState({});

    const handleFetchLogs = useCallback((service, instanceName) => {
        const key = `${service}:${instanceName}`;
        instancesAPI
            .fetchInstanceLogs(instanceName, { limit: 50 })
            .then(res => {
                setLogsData(prev => ({
                    ...prev,
                    [key]: res?.data?.logs || [],
                }));
            })
            .catch(() => {});
    }, []);

    const handleFetchLibraries = useCallback((service, instanceName) => {
        const key = `${service}:${instanceName}`;
        instancesAPI
            .fetchPlexLibraries(instanceName)
            .then(res => {
                const libs = res?.data?.libraries || res?.data || [];
                setLibrariesData(prev => ({ ...prev, [key]: libs }));
            })
            .catch(() => {});
    }, []);

    const handleToggleInstance = useCallback(
        async (instanceName, enabled) => {
            try {
                await instancesAPI.toggleInstance(instanceName, enabled);
                toast.success(`${instanceName} ${enabled ? 'enabled' : 'disabled'}`);
                refreshInstances();
            } catch {
                toast.error(`Failed to toggle ${instanceName}`);
            }
        },
        [toast, refreshInstances]
    );

    const handleRefreshInstance = useCallback(
        async instanceName => {
            try {
                await instancesAPI.refreshInstance(instanceName);
                toast.success(`${instanceName} data refreshed`);
            } catch {
                toast.error(`Failed to refresh ${instanceName}`);
            }
        },
        [toast]
    );

    // Track if bulk testing has been performed for this page load
    const bulkTestingCompletedRef = useRef(false);

    // Modal state
    const [addModalOpen, setAddModalOpen] = useState(false);
    const [editModalOpen, setEditModalOpen] = useState(false);
    const [deleteModalOpen, setDeleteModalOpen] = useState(false);
    const [modalServiceType, setModalServiceType] = useState(null);
    const [modalInstanceData, setModalInstanceData] = useState(null);
    const [formData, setFormData] = useState({});
    const [formErrors, setFormErrors] = useState({});
    const [isTesting, setIsTesting] = useState(false);
    const [isSaving, setIsSaving] = useState(false);

    // Calculate statistics
    const statistics = useMemo(() => {
        if (!instances) return [];

        // Composite service:name keys so a name shared across services (e.g. a
        // radarr and a sonarr both called "main") doesn't collide in the status maps.
        const allInstanceKeys = [
            ...Object.keys(instances?.radarr || {}).map(n => `radarr:${n}`),
            ...Object.keys(instances?.sonarr || {}).map(n => `sonarr:${n}`),
            ...Object.keys(instances?.lidarr || {}).map(n => `lidarr:${n}`),
            ...Object.keys(instances?.plex || {}).map(n => `plex:${n}`),
        ];

        const connectedCount = allInstanceKeys.filter(key => connectionStatus[key]?.success).length;

        const failedCount = allInstanceKeys.filter(
            key => connectionStatus[key]?.success === false
        ).length;

        return [
            {
                label: 'Total Instances',
                value: allInstanceKeys.length,
                colorClass: 'text-fg',
            },
            { label: 'Connected', value: connectedCount, colorClass: 'text-success' },
            { label: 'Failed', value: failedCount, colorClass: 'text-error' },
        ];
    }, [instances, connectionStatus]);

    // Load supported instance types from backend (with hardcoded fallback)
    const { data: supportedTypesData } = useApiData({
        apiFunction: instancesAPI.fetchSupportedTypes,
        options: { showErrorToast: false },
    });

    const services = useMemo(() => {
        const types = supportedTypesData?.data?.types || supportedTypesData?.data;
        if (Array.isArray(types) && types.length > 0) {
            return types.map(t =>
                typeof t === 'string'
                    ? { type: t, label: humanize(t) }
                    : { type: t.type || t.name, label: t.label || humanize(t.type || t.name) }
            );
        }
        // Fallback if endpoint returns unexpected shape
        return [
            { type: 'radarr', label: 'Radarr' },
            { type: 'sonarr', label: 'Sonarr' },
            { type: 'lidarr', label: 'Lidarr' },
            { type: 'plex', label: 'Plex' },
        ];
    }, [supportedTypesData]);

    // Cache type schemas as they're requested
    const [typeSchemas, setTypeSchemas] = useState({});
    const loadTypeSchema = useCallback(
        async instanceType => {
            if (typeSchemas[instanceType]) return typeSchemas[instanceType];
            try {
                const result = await instancesAPI.fetchTypeSchema(instanceType);
                const schema = result?.data || null;
                setTypeSchemas(prev => ({ ...prev, [instanceType]: schema }));
                return schema;
            } catch {
                return null;
            }
        },
        [typeSchemas]
    );

    /**
     * Handle add instance action
     * @param {string} serviceType - Service type (radarr|sonarr|plex)
     */
    const handleAdd = useCallback(
        serviceType => {
            setModalServiceType(serviceType);
            setFormData({});
            setFormErrors({});
            setAddModalOpen(true);
            // Pre-load schema for this service type
            loadTypeSchema(serviceType);
        },
        [loadTypeSchema]
    );

    /**
     * Handle edit instance action
     * @param {string} serviceType - Service type (radarr|sonarr|plex)
     * @param {string} instanceName - Instance name
     * @param {string} instanceUrl - Instance URL
     */
    const handleEdit = useCallback(
        (serviceType, instanceName, instanceUrl) => {
            const instanceConfig = instances?.[serviceType]?.[instanceName];
            setModalServiceType(serviceType);
            setModalInstanceData({ name: instanceName, url: instanceUrl });
            setFormData({
                name: instanceName,
                url: instanceUrl,
                api: instanceConfig?.api || '',
                webhook_force_reupload: !!instanceConfig?.webhook_force_reupload,
            });
            setFormErrors({});
            setEditModalOpen(true);
        },
        [instances]
    );

    /**
     * Handle delete instance action
     * @param {string} serviceType - Service type (radarr|sonarr|plex)
     * @param {string} instanceName - Instance name
     * @param {string} instanceUrl - Instance URL
     */
    const handleDelete = useCallback((serviceType, instanceName, instanceUrl) => {
        setModalServiceType(serviceType);
        setModalInstanceData({ name: instanceName, url: instanceUrl });
        setDeleteModalOpen(true);
    }, []);

    /**
     * Validate form data
     * @returns {boolean} True if valid
     */
    const validateForm = useCallback(() => {
        const errors = {};
        INSTANCE_SCHEMA.filter(
            field => !field.serviceTypes || field.serviceTypes.includes(modalServiceType)
        ).forEach(field => {
            if (field.required && !formData[field.key]) {
                errors[field.key] = `${field.label} is required`;
            }
        });
        setFormErrors(errors);
        return Object.keys(errors).length === 0;
    }, [formData, modalServiceType]);

    /**
     * Handle form submission for Add/Edit
     */
    const handleFormSubmit = useCallback(
        async isEdit => {
            if (!validateForm()) {
                toast.error('Please fill in all required fields');
                return;
            }

            setIsTesting(true);

            try {
                // Test connection first
                const testResult = await instancesAPI.testInstanceConfig({
                    service: modalServiceType,
                    name: formData.name,
                    url: formData.url,
                    api: formData.api,
                });

                setIsTesting(false);

                // If test passed, save the configuration
                if (testResult) {
                    setIsSaving(true);

                    try {
                        const instanceData = {
                            service: modalServiceType,
                            name: formData.name,
                            url: formData.url,
                            api: formData.api,
                            webhook_force_reupload: !!formData.webhook_force_reupload,
                        };

                        if (isEdit) {
                            // Update existing instance
                            await instancesAPI.updateInstance(modalInstanceData.name, instanceData);
                        } else {
                            // Create new instance
                            await instancesAPI.createInstance(instanceData);
                        }

                        toast.success(
                            `Instance ${isEdit ? 'updated' : 'added'} successfully: ${formData.name}`
                        );
                        setIsSaving(false);

                        // Close modal and refresh (bypass cache to show updated data)
                        setAddModalOpen(false);
                        setEditModalOpen(false);
                        refreshInstances({ useCache: false });
                    } catch (saveError) {
                        setIsSaving(false);
                        console.error('Instance save error:', saveError);
                        toast.error(
                            saveError.message || `Failed to ${isEdit ? 'update' : 'add'} instance`
                        );
                    }
                }
            } catch (error) {
                setIsTesting(false);
                setIsSaving(false);
                console.error('Instance save error:', error);
                toast.error(error.message || `Failed to ${isEdit ? 'update' : 'add'} instance`);
            }
        },
        [validateForm, modalServiceType, formData, modalInstanceData, toast, refreshInstances]
    );

    /**
     * Handle delete confirmation
     */
    const handleConfirmDelete = useCallback(async () => {
        setIsSaving(true);

        try {
            // Call actual delete endpoint
            await instancesAPI.deleteInstance(modalInstanceData.name, modalServiceType);

            toast.success(`Instance deleted successfully: ${modalInstanceData.name}`);
            setIsSaving(false);
            setDeleteModalOpen(false);
            refreshInstances({ useCache: false });
        } catch (error) {
            setIsSaving(false);
            console.error('Instance delete error:', error);
            toast.error(error.message || 'Failed to delete instance');
        }
    }, [modalInstanceData, modalServiceType, toast, refreshInstances]);

    /**
     * Handle field change
     */
    const handleFieldChange = useCallback((fieldKey, value) => {
        setFormData(prev => ({ ...prev, [fieldKey]: value }));
        // Clear error for this field
        setFormErrors(prev => {
            const newErrors = { ...prev };
            delete newErrors[fieldKey];
            return newErrors;
        });
    }, []);

    /**
     * Handle connection test for an instance
     * @param {string} serviceType - Service type (radarr|sonarr|plex)
     * @param {string} instanceName - Instance name
     * @param {Object} instanceData - Instance configuration data
     * @param {boolean} isBulkTest - Whether this is part of bulk testing (suppresses toasts)
     */
    const handleTest = useCallback(
        async (serviceType, instanceName, instanceData, isBulkTest = false) => {
            // Add to testing set
            setTestingInstances(prev => new Set([...prev, `${serviceType}:${instanceName}`]));

            try {
                const result = await instancesAPI.testInstanceConfig({
                    service: serviceType,
                    name: instanceName,
                    url: instanceData.url,
                    api: instanceData.api,
                });

                // Success
                const successMessage =
                    result?.message || result?.data?.message || 'Connection successful';

                setConnectionStatus(prev => ({
                    ...prev,
                    [`${serviceType}:${instanceName}`]: {
                        success: true,
                        message: successMessage,
                        timestamp: Date.now(),
                    },
                }));

                // Only show toast for manual tests (not bulk tests)
                if (!isBulkTest) {
                    try {
                        toast.success(`${instanceName}: ${successMessage}`);
                    } catch (toastError) {
                        console.warn('Toast notification failed:', toastError);
                        // Don't rethrow - connection test was successful
                    }
                }
            } catch (error) {
                // Failure - Handle case where error might be undefined or have unexpected structure
                console.error('Connection test error for', instanceName, ':', error);

                let errorMessage = 'Connection failed';
                if (error && typeof error === 'object') {
                    errorMessage =
                        error.message || error.error || String(error) || 'Connection failed';
                } else if (error) {
                    errorMessage = String(error);
                }

                setConnectionStatus(prev => ({
                    ...prev,
                    [`${serviceType}:${instanceName}`]: {
                        success: false,
                        message: errorMessage,
                        timestamp: Date.now(),
                    },
                }));

                // Only show toast for manual tests (not bulk tests)
                if (!isBulkTest) {
                    toast.error(`${instanceName}: ${errorMessage}`);
                }
            } finally {
                // Remove from testing set
                setTestingInstances(prev => {
                    const next = new Set(prev);
                    next.delete(`${serviceType}:${instanceName}`);
                    return next;
                });
            }
        },
        [toast]
    );

    /**
     * Handle sync for an instance
     * @param {string} serviceType - Service type (radarr|sonarr|plex)
     * @param {string} instanceName - Instance name
     */
    const handleSync = useCallback(
        async (serviceType, instanceName) => {
            // Add to syncing set
            setSyncingInstances(prev => new Set([...prev, `${serviceType}:${instanceName}`]));

            try {
                await instancesAPI.syncInstance(instanceName);
                toast.success(`Sync initiated for ${instanceName}`);
            } catch (error) {
                console.error('Instance sync error for', instanceName, ':', error);
                const errorMessage =
                    error?.message || error?.error || String(error) || 'Sync failed';
                toast.error(`${instanceName}: ${errorMessage}`);
            } finally {
                setSyncingInstances(prev => {
                    const next = new Set(prev);
                    next.delete(`${serviceType}:${instanceName}`);
                    return next;
                });
            }
        },
        [toast]
    );

    /**
     * Perform bulk testing of all instances ONCE when page loads and instances data is available
     */
    useEffect(() => {
        if (!instances || bulkTestingCompletedRef.current) return;

        // Mark bulk testing as completed to prevent repeated execution
        bulkTestingCompletedRef.current = true;

        // Collect all instances to test
        const instancesToTest = [];

        services.forEach(service => {
            const serviceInstances = instances[service.type] || {};
            Object.entries(serviceInstances).forEach(([name, data]) => {
                instancesToTest.push({
                    serviceType: service.type,
                    instanceName: name,
                    instanceData: data,
                });
            });
        });

        // Test all instances with isBulkTest=true to suppress toasts
        instancesToTest.forEach(({ serviceType, instanceName, instanceData }) => {
            handleTest(serviceType, instanceName, instanceData, true);
        });

        // Fetch health and stats for all instances (best-effort, no toasts)
        instancesToTest.forEach(({ serviceType, instanceName }) => {
            instancesAPI
                .fetchHealthStatus(instanceName)
                .then(res => {
                    if (res?.data) {
                        setHealthData(prev => ({
                            ...prev,
                            [`${serviceType}:${instanceName}`]: res.data,
                        }));
                    }
                })
                .catch(() => {});
            instancesAPI
                .fetchStatistics(instanceName, { service_type: serviceType })
                .then(res => {
                    if (res?.data) {
                        setStatsData(prev => ({
                            ...prev,
                            [`${serviceType}:${instanceName}`]: res.data,
                        }));
                    }
                })
                .catch(() => {});
        });
    }, [instances, handleTest, services]);

    // Loading state
    if (isLoading) {
        return (
            <div className="p-3 sm:p-6 max-w-screen-xl mx-auto">
                <PageHeader
                    title="Instances"
                    description="Radarr, Sonarr, Lidarr, and Plex connections."
                    badge={2}
                    icon="dns"
                />
                <div className="text-center py-12">
                    <p className="text-fg-muted">Loading instances...</p>
                </div>
            </div>
        );
    }

    // Error state
    if (error) {
        return (
            <div className="p-3 sm:p-6 max-w-screen-xl mx-auto">
                <PageHeader
                    title="Instances"
                    description="Radarr, Sonarr, Lidarr, and Plex connections."
                    badge={2}
                    icon="dns"
                />
                <div className="text-center py-12">
                    <p className="text-error">Error loading instances: {error.message}</p>
                    <Button variant="primary" onClick={refreshInstances} className="mt-4">
                        Retry
                    </Button>
                </div>
            </div>
        );
    }

    return (
        <div className="max-w-screen-xl mx-auto flex flex-col gap-6">
            {/* Page Header */}
            <PageHeader
                title="Instances"
                description="Radarr, Sonarr, Lidarr and Plex connections."
            />

            {/* Statistics */}
            <StatGrid columns={3}>
                {statistics.map(stat => (
                    <StatCard
                        key={stat.label}
                        label={stat.label}
                        value={stat.value}
                        colorClass={stat.colorClass}
                    />
                ))}
            </StatGrid>

            {/* Auto-sync cadence — small, secondary control. Reconciles the
                media cache from these instances (a safety-net behind webhooks);
                full library stats live on the Statistics page. */}
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-fg-subtle">
                <span className="material-symbols-outlined text-[16px]" aria-hidden="true">
                    sync
                </span>
                <span>Auto-sync library from instances</span>
                <select
                    className="bg-surface border border-border rounded-md px-2 py-1 text-fg text-[13px] disabled:opacity-50"
                    value={(SYNC_PRESETS.find(p => p.value === syncSchedule) || {}).key ?? 'custom'}
                    disabled={!syncScheduleLoaded || syncScheduleSaving}
                    onChange={e => {
                        const preset = SYNC_PRESETS.find(p => p.key === e.target.value);
                        if (preset) handleSyncPresetChange(preset.value);
                    }}
                >
                    {SYNC_PRESETS.map(p => (
                        <option key={p.key} value={p.key}>
                            {p.label}
                        </option>
                    ))}
                    {!SYNC_PRESETS.some(p => p.value === syncSchedule) && (
                        <option value="custom">Custom ({syncSchedule})</option>
                    )}
                </select>
                {syncScheduleSaving && <span>saving…</span>}
            </div>

            {/* Service Sections */}
            {services.map(service => (
                <div key={service.type}>
                    {/* Service Header */}
                    <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                        <h2 className="font-display text-[18px] font-semibold text-fg flex items-center gap-2">
                            <ServiceIcon service={service.type} size="large" />
                            {service.label} Instances
                        </h2>
                        <Button variant="primary" onClick={() => handleAdd(service.type)}>
                            + Add {service.label}
                        </Button>
                    </div>

                    {/* Instance rows */}
                    <div className="flex flex-col gap-3">
                        {Object.entries(instances?.[service.type] || {}).map(([name, data]) => (
                            <InstanceCard
                                key={name}
                                instance={{ name, ...data }}
                                serviceType={service.type}
                                connectionStatus={connectionStatus[`${service.type}:${name}`]}
                                healthStatus={healthData[`${service.type}:${name}`]}
                                instanceStats={statsData[`${service.type}:${name}`]}
                                instanceLogs={logsData[`${service.type}:${name}`]}
                                plexLibraries={librariesData[`${service.type}:${name}`]}
                                isTesting={testingInstances.has(`${service.type}:${name}`)}
                                isSyncing={syncingInstances.has(`${service.type}:${name}`)}
                                onTest={() => handleTest(service.type, name, data)}
                                onSync={() => handleSync(service.type, name)}
                                onEdit={() => handleEdit(service.type, name, data.url)}
                                onDelete={() => handleDelete(service.type, name, data.url)}
                                onFetchLogs={() => handleFetchLogs(service.type, name)}
                                onFetchLibraries={() => handleFetchLibraries(service.type, name)}
                                onToggle={handleToggleInstance}
                                onRefresh={handleRefreshInstance}
                            />
                        ))}
                    </div>

                    {/* Empty State */}
                    {Object.keys(instances?.[service.type] || {}).length === 0 && (
                        <div className="text-center py-12 text-fg-muted">
                            <p>No {service.label} instances configured</p>
                        </div>
                    )}
                </div>
            ))}

            {/* Add Instance Modal */}
            <Modal isOpen={addModalOpen} onClose={() => setAddModalOpen(false)} size="medium">
                <Modal.Header>
                    Add {modalServiceType?.charAt(0).toUpperCase() + modalServiceType?.slice(1)}{' '}
                    Instance
                </Modal.Header>
                <Modal.Body>
                    <div className="flex flex-col gap-4">
                        {INSTANCE_SCHEMA.filter(
                            field =>
                                !field.serviceTypes || field.serviceTypes.includes(modalServiceType)
                        ).map(field => {
                            const FieldComponent = FieldRegistry.getField(field.type);
                            const isToggle = field.type === 'toggle' || field.type === 'check_box';
                            return (
                                <FieldComponent
                                    key={field.key}
                                    field={field}
                                    value={
                                        isToggle ? !!formData[field.key] : formData[field.key] || ''
                                    }
                                    onChange={value => handleFieldChange(field.key, value)}
                                    errorMessage={formErrors[field.key]}
                                    highlightInvalid={!!formErrors[field.key]}
                                />
                            );
                        })}
                    </div>
                </Modal.Body>
                <Modal.Footer>
                    <Button
                        variant="secondary"
                        onClick={() => setAddModalOpen(false)}
                        disabled={isTesting || isSaving}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={() => handleFormSubmit(false)}
                        disabled={isTesting || isSaving}
                    >
                        {isTesting ? 'Testing...' : isSaving ? 'Saving...' : 'Add Instance'}
                    </Button>
                </Modal.Footer>
            </Modal>

            {/* Edit Instance Modal */}
            <Modal isOpen={editModalOpen} onClose={() => setEditModalOpen(false)} size="medium">
                <Modal.Header>
                    Edit {modalServiceType?.charAt(0).toUpperCase() + modalServiceType?.slice(1)}{' '}
                    Instance
                </Modal.Header>
                <Modal.Body>
                    <div className="flex flex-col gap-4">
                        {INSTANCE_SCHEMA.filter(
                            field =>
                                !field.serviceTypes || field.serviceTypes.includes(modalServiceType)
                        ).map(field => {
                            const FieldComponent = FieldRegistry.getField(field.type);
                            const isToggle = field.type === 'toggle' || field.type === 'check_box';
                            // Reveal resolves against the SAVED instance (keyed by
                            // its stored name), not whatever name is typed in the
                            // form — the persisted config is what holds the secret.
                            const secretField =
                                field.type === 'password' && modalInstanceData?.name
                                    ? {
                                          ...field,
                                          secretPath: `instances.${modalServiceType}.${modalInstanceData.name}.${field.key}`,
                                      }
                                    : field;
                            return (
                                <FieldComponent
                                    key={field.key}
                                    field={secretField}
                                    value={
                                        isToggle ? !!formData[field.key] : formData[field.key] || ''
                                    }
                                    onChange={value => handleFieldChange(field.key, value)}
                                    errorMessage={formErrors[field.key]}
                                    highlightInvalid={!!formErrors[field.key]}
                                />
                            );
                        })}
                    </div>
                </Modal.Body>
                <Modal.Footer>
                    <Button
                        variant="secondary"
                        onClick={() => setEditModalOpen(false)}
                        disabled={isTesting || isSaving}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={() => handleFormSubmit(true)}
                        disabled={isTesting || isSaving}
                    >
                        {isTesting ? 'Testing...' : isSaving ? 'Saving...' : 'Save Changes'}
                    </Button>
                </Modal.Footer>
            </Modal>

            {/* Delete Instance Modal */}
            <Modal isOpen={deleteModalOpen} onClose={() => setDeleteModalOpen(false)} size="small">
                <Modal.Header>Confirm Delete</Modal.Header>
                <Modal.Body>
                    <div className="flex flex-col gap-4">
                        <p className="text-base">Are you sure you want to delete this instance?</p>
                        <div className="p-4 bg-surface-alt rounded-lg border border-border">
                            <div className="flex flex-col gap-2 text-sm">
                                <div>
                                    <span className="text-fg-muted">Service:</span>{' '}
                                    <span className="font-medium">
                                        {modalServiceType?.charAt(0).toUpperCase() +
                                            modalServiceType?.slice(1)}
                                    </span>
                                </div>
                                <div>
                                    <span className="text-fg-muted">Instance:</span>{' '}
                                    <span className="font-medium">
                                        {humanize(modalInstanceData?.name)}
                                    </span>
                                </div>
                                <div>
                                    <span className="text-fg-muted">URL:</span>{' '}
                                    <span className="font-medium">{modalInstanceData?.url}</span>
                                </div>
                            </div>
                        </div>
                        <p className="text-sm text-warning">⚠️ This action cannot be undone.</p>
                    </div>
                </Modal.Body>
                <Modal.Footer>
                    <Button
                        variant="secondary"
                        onClick={() => setDeleteModalOpen(false)}
                        disabled={isSaving}
                    >
                        Cancel
                    </Button>
                    <Button variant="danger" onClick={handleConfirmDelete} disabled={isSaving}>
                        {isSaving ? 'Deleting...' : 'Delete Instance'}
                    </Button>
                </Modal.Footer>
            </Modal>
        </div>
    );
};
