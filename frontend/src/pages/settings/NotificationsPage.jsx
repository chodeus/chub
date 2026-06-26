import { useMemo, useState, useCallback } from 'react';
import { PageHeader } from '../../components/ui/PageHeader';
import { StatGrid } from '../../components/statistics';
import { StatCard, ServiceIcon } from '../../components/ui';
import { Button } from '../../components/ui/button/Button';
import { Modal } from '../../components/modals/Modal';
import { useApiData } from '../../hooks/useApiData';
import { notificationsAPI } from '../../utils/api/notifications';
import { NotificationCard } from '../../components/notifications/NotificationCard';
import { FieldRegistry } from '../../components/fields/FieldRegistry';
import { NOTIFICATIONS_SCHEMA } from '../../utils/constants/notifications_schema';
import { useToast } from '../../contexts/ToastContext';
import { humanize } from '../../utils/tools';
import { moduleOrder } from '../../utils/constants/constants';

// Every notifiable channel (matches the backend ConfigNotifications model):
// all modules in display order plus the global "main" error channel, minus the
// non-notifiable "general" section.
const NOTIFY_MODULES = moduleOrder.filter(m => m !== 'general');

/**
 * Notifications Management page
 *
 * Manages notification service configurations for all CHUB modules:
 * - Discord and Notifiarr notification services
 * - Per-module notification settings
 * - Service testing and validation
 *
 * @returns {JSX.Element} Notifications page component
 */
export const NotificationsPage = () => {
    const toast = useToast();

    // Data loading
    const {
        data: notifications,
        isLoading,
        error,
        execute: refreshNotifications,
    } = useApiData({
        apiFunction: notificationsAPI.fetchNotifications,
    });

    // Modal state
    const [addModalOpen, setAddModalOpen] = useState(false);
    const [editModalOpen, setEditModalOpen] = useState(false);
    const [deleteModalOpen, setDeleteModalOpen] = useState(false);
    const [selectedModule, setSelectedModule] = useState(null);
    const [selectedServiceType, setSelectedServiceType] = useState(null);
    const [moduleToDelete, setModuleToDelete] = useState(null);
    const [serviceToDelete, setServiceToDelete] = useState(null);
    const [formData, setFormData] = useState({});
    const [formErrors, setFormErrors] = useState({});
    const [isSaving, setIsSaving] = useState(false);

    // Testing state
    const [testingServices, setTestingServices] = useState(new Set());

    // Bulk "apply to multiple modules" state
    const [bulkOpen, setBulkOpen] = useState(false);
    const [bulkService, setBulkService] = useState(null);
    const [bulkForm, setBulkForm] = useState({});
    const [bulkErrors, setBulkErrors] = useState({});
    const [bulkModules, setBulkModules] = useState(() => new Set(NOTIFY_MODULES));
    const [bulkSaving, setBulkSaving] = useState(false);

    /**
     * Handle add notification action
     * @param {string} moduleName - Module to add notification for
     */
    const handleAdd = useCallback(moduleName => {
        setSelectedModule(moduleName);
        setSelectedServiceType(null);
        setFormData({});
        setFormErrors({});
        setAddModalOpen(true);
    }, []);

    /**
     * Handle edit notification action
     * @param {string} moduleName - Module name
     * @param {string} serviceType - Service type to edit
     * @param {Object} config - Existing configuration
     */
    const handleEdit = useCallback((moduleName, serviceType, config) => {
        setSelectedModule(moduleName);
        setSelectedServiceType(serviceType);
        setFormData({ ...config }); // Prepopulate with existing data
        setFormErrors({});
        setEditModalOpen(true);
    }, []);

    /**
     * Handle delete notification action
     * @param {string} moduleName - Module name
     * @param {string} serviceType - Service type to delete
     */
    const handleDelete = useCallback((moduleName, serviceType) => {
        setModuleToDelete(moduleName);
        setServiceToDelete(serviceType);
        setDeleteModalOpen(true);
    }, []);

    /**
     * Handle test notification
     * @param {string} moduleName - Module name
     * @param {string} serviceType - Service type
     * @param {Object} config - Notification configuration
     */
    const handleTest = useCallback(
        async (moduleName, serviceType, config) => {
            const testKey = `${moduleName}-${serviceType}`;

            // Add to testing set
            setTestingServices(prev => new Set([...prev, testKey]));

            try {
                // Call test endpoint with correct payload structure
                const result = await notificationsAPI.testNotification({
                    module: moduleName,
                    notifications: {
                        [serviceType]: config,
                    },
                });

                // Success
                const successMessage = result?.message || 'Test notification sent successfully';
                toast.success(`${serviceType}: ${successMessage}`);
            } catch (error) {
                console.error('Test notification error:', error);
                const errorMessage = error.message || 'Test notification failed';
                toast.error(`${serviceType}: ${errorMessage}`);
            } finally {
                // Remove from testing set
                setTestingServices(prev => {
                    const next = new Set(prev);
                    next.delete(testKey);
                    return next;
                });
            }
        },
        [toast]
    );

    /**
     * Validate form data
     * @returns {boolean} True if valid
     */
    const validateForm = useCallback(() => {
        if (!selectedServiceType) return false;

        const errors = {};
        const serviceSchema = NOTIFICATIONS_SCHEMA.find(s => s.type === selectedServiceType);

        serviceSchema?.fields.forEach(field => {
            if (field.required && !formData[field.key]) {
                errors[field.key] = `${field.label} is required`;
            }
            if (field.validate && formData[field.key] && !field.validate(formData[field.key])) {
                errors[field.key] = `${field.label} format is invalid`;
            }
        });

        setFormErrors(errors);
        return Object.keys(errors).length === 0;
    }, [selectedServiceType, formData]);

    /**
     * Handle field change
     */
    const handleFieldChange = useCallback((fieldKey, value) => {
        setFormData(prev => ({ ...prev, [fieldKey]: value }));
        setFormErrors(prev => {
            const newErrors = { ...prev };
            delete newErrors[fieldKey];
            return newErrors;
        });
    }, []);

    /**
     * Handle form submission for Add
     */
    const handleFormSubmit = useCallback(async () => {
        if (!validateForm()) {
            toast.error('Please fill in all required fields correctly');
            return;
        }

        setIsSaving(true);

        try {
            await notificationsAPI.updateNotification({
                module: selectedModule,
                service_type: selectedServiceType,
                config: formData,
            });

            toast.success(
                `${selectedServiceType} notification added successfully for ${selectedModule}`
            );
            setIsSaving(false);

            setAddModalOpen(false);
            setSelectedServiceType(null);
            refreshNotifications({ useCache: false });
        } catch (error) {
            setIsSaving(false);
            console.error('Notification save error:', error);
            toast.error(error.message || 'Failed to add notification');
        }
    }, [validateForm, selectedModule, selectedServiceType, formData, toast, refreshNotifications]);

    /**
     * Handle edit form submission
     */
    const handleEditSubmit = useCallback(async () => {
        if (!validateForm()) {
            toast.error('Please fill in all required fields correctly');
            return;
        }

        setIsSaving(true);

        try {
            await notificationsAPI.updateNotification({
                module: selectedModule,
                service_type: selectedServiceType,
                config: formData,
            });

            toast.success(`${selectedServiceType} notification updated successfully`);
            setIsSaving(false);

            setEditModalOpen(false);
            refreshNotifications({ useCache: false });
        } catch (error) {
            setIsSaving(false);
            console.error('Notification update error:', error);
            toast.error(error.message || 'Failed to update notification');
        }
    }, [validateForm, selectedModule, selectedServiceType, formData, toast, refreshNotifications]);

    /**
     * Handle delete confirmation
     */
    const handleConfirmDelete = useCallback(async () => {
        if (!moduleToDelete || !serviceToDelete) return;

        setIsSaving(true);

        try {
            await notificationsAPI.deleteNotification(moduleToDelete, serviceToDelete);

            toast.success(`${serviceToDelete} notification deleted successfully`);
            setIsSaving(false);
            setDeleteModalOpen(false);

            refreshNotifications({ useCache: false });
        } catch (error) {
            setIsSaving(false);
            console.error('Notification delete error:', error);
            toast.error(error.message || 'Failed to delete notification');
        }
    }, [moduleToDelete, serviceToDelete, toast, refreshNotifications]);

    /**
     * Open the "apply to multiple modules" flow (defaults to all modules).
     */
    const openBulk = useCallback(() => {
        setBulkService(null);
        setBulkForm({});
        setBulkErrors({});
        setBulkModules(new Set(NOTIFY_MODULES));
        setBulkOpen(true);
    }, []);

    const toggleBulkModule = useCallback(key => {
        setBulkModules(prev => {
            const next = new Set(prev);
            next.has(key) ? next.delete(key) : next.add(key);
            return next;
        });
    }, []);

    const handleBulkFieldChange = useCallback((fieldKey, value) => {
        setBulkForm(prev => ({ ...prev, [fieldKey]: value }));
        setBulkErrors(prev => {
            const next = { ...prev };
            delete next[fieldKey];
            return next;
        });
    }, []);

    /**
     * Apply one service config to every selected module via the existing
     * per-module endpoint (no bulk backend route needed).
     */
    const handleBulkSubmit = useCallback(async () => {
        const errors = {};
        const serviceSchema = NOTIFICATIONS_SCHEMA.find(s => s.type === bulkService);
        serviceSchema?.fields.forEach(field => {
            if (field.required && !bulkForm[field.key]) {
                errors[field.key] = `${field.label} is required`;
            }
            if (field.validate && bulkForm[field.key] && !field.validate(bulkForm[field.key])) {
                errors[field.key] = `${field.label} format is invalid`;
            }
        });
        setBulkErrors(errors);
        if (Object.keys(errors).length > 0) {
            toast.error('Please fill in all required fields correctly');
            return;
        }
        if (bulkModules.size === 0) {
            toast.error('Select at least one module to apply to');
            return;
        }

        setBulkSaving(true);
        const targets = [...bulkModules];
        const results = await Promise.allSettled(
            targets.map(m =>
                notificationsAPI.updateNotification({
                    module: m,
                    service_type: bulkService,
                    config: bulkForm,
                })
            )
        );
        setBulkSaving(false);

        const failed = results.filter(r => r.status === 'rejected').length;
        const ok = targets.length - failed;
        if (failed === 0) {
            toast.success(`${bulkService} applied to ${ok} module${ok === 1 ? '' : 's'}`);
        } else if (ok === 0) {
            toast.error(`Failed to apply to all ${failed} module(s)`);
        } else {
            toast.error(`Applied to ${ok} module(s); ${failed} failed`);
        }
        setBulkOpen(false);
        refreshNotifications({ useCache: false });
    }, [bulkService, bulkForm, bulkModules, toast, refreshNotifications]);

    // Calculate statistics
    const statistics = useMemo(() => {
        if (!notifications?.data?.notifications) {
            return [
                { label: 'Modules Configured', value: 0, valueColor: 'primary' },
                { label: 'Total Services', value: 0, valueColor: '' },
                { label: 'Discord', value: 0, valueColor: '' },
                { label: 'Notifiarr', value: 0, valueColor: '' },
            ];
        }

        const notificationData = notifications.data.notifications;
        const moduleKeys = Object.keys(notificationData);

        let totalServices = 0;
        let discordCount = 0;
        let notifiarrCount = 0;

        // Count services across all modules
        moduleKeys.forEach(moduleKey => {
            const moduleNotifications = notificationData[moduleKey];

            if (moduleNotifications.discord) {
                discordCount++;
                totalServices++;
            }
            if (moduleNotifications.notifiarr) {
                notifiarrCount++;
                totalServices++;
            }
        });

        return [
            {
                label: 'Modules Configured',
                value: moduleKeys.length,
                valueColor: 'primary',
            },
            {
                label: 'Total Services',
                value: totalServices,
                valueColor: '',
            },
            {
                label: 'Discord',
                value: discordCount,
                valueColor: '',
            },
            {
                label: 'Notifiarr',
                value: notifiarrCount,
                valueColor: '',
            },
        ];
    }, [notifications]);

    // Loading state
    if (isLoading) {
        return (
            <div className="p-6 max-w-screen-xl mx-auto">
                <PageHeader
                    title="Notifications"
                    description="Discord and Notifiarr alerts."
                    badge={3}
                    icon="notifications"
                />
                <div className="text-center py-12">
                    <p className="text-fg-muted">Loading notifications...</p>
                </div>
            </div>
        );
    }

    // Error state
    if (error) {
        return (
            <div className="p-6 max-w-screen-xl mx-auto">
                <PageHeader
                    title="Notifications"
                    description="Discord and Notifiarr alerts."
                    badge={3}
                    icon="notifications"
                />
                <div className="text-center py-12">
                    <p className="text-error">Error loading notifications: {error.message}</p>
                    <Button variant="primary" onClick={refreshNotifications} className="mt-4">
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
                title="Notifications"
                description="Where CHUB sends run summaries and failure alerts."
            />

            {/* Statistics */}
            <StatGrid columns={5}>
                {statistics.map(stat => (
                    <StatCard
                        key={stat.label}
                        label={stat.label}
                        value={stat.value}
                        valueColor={stat.valueColor}
                    />
                ))}
            </StatGrid>

            {/* Bulk action — apply one webhook to many modules at once */}
            <div className="flex justify-end">
                <Button variant="secondary" onClick={openBulk}>
                    + Apply to multiple modules
                </Button>
            </div>

            {/* Module Sections */}
            {notifications?.data?.notifications &&
            Object.keys(notifications.data.notifications).length > 0 ? (
                Object.entries(notifications.data.notifications).map(
                    ([moduleName, moduleNotifs]) => (
                        <div key={moduleName} className="mb-8">
                            {/* Module Header */}
                            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-4">
                                <h2 className="text-2xl font-semibold text-fg">
                                    {humanize(moduleName)}
                                </h2>
                                <Button variant="primary" onClick={() => handleAdd(moduleName)}>
                                    + Add Notification
                                </Button>
                            </div>

                            {/* Notification Cards Grid */}
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                                {Object.entries(moduleNotifs).map(([serviceType, config]) => (
                                    <NotificationCard
                                        key={`${moduleName}-${serviceType}`}
                                        moduleName={moduleName}
                                        serviceType={serviceType}
                                        config={config}
                                        onEdit={handleEdit}
                                        onDelete={handleDelete}
                                        onTest={handleTest}
                                        isTesting={testingServices.has(
                                            `${moduleName}-${serviceType}`
                                        )}
                                    />
                                ))}
                            </div>
                        </div>
                    )
                )
            ) : (
                <div className="text-center py-12 text-fg-muted">
                    <p>No notifications configured</p>
                    <p className="text-sm mt-2">Add a notification to get started</p>
                </div>
            )}

            {/* Add Notification - Step 1: Service Type Selection */}
            {addModalOpen && !selectedServiceType && (
                <Modal
                    isOpen={true}
                    onClose={() => {
                        setAddModalOpen(false);
                        setSelectedModule(null);
                    }}
                    size="small"
                >
                    <Modal.Header>Select Notification Service</Modal.Header>
                    <Modal.Body>
                        <div className="flex flex-col gap-4">
                            {NOTIFICATIONS_SCHEMA.map(service => {
                                const alreadyConfigured =
                                    notifications?.data?.notifications?.[selectedModule]?.[
                                        service.type
                                    ];

                                return (
                                    <Button
                                        key={service.type}
                                        variant={alreadyConfigured ? 'muted' : 'ghost'}
                                        onClick={() => {
                                            if (!alreadyConfigured) {
                                                setSelectedServiceType(service.type);
                                                setFormData({});
                                            }
                                        }}
                                        disabled={alreadyConfigured}
                                        fullWidth
                                        className="justify-start"
                                    >
                                        <div className="flex items-center gap-3 w-full">
                                            {/* Icon */}
                                            <div className="flex items-center justify-center min-w-6">
                                                <ServiceIcon service={service.type} size="medium" />
                                            </div>

                                            {/* Label */}
                                            <div className="flex-1 text-left">
                                                <div className="font-medium">{service.label}</div>
                                                {alreadyConfigured && (
                                                    <div className="text-fg-muted text-sm">
                                                        Already configured
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    </Button>
                                );
                            })}
                        </div>
                    </Modal.Body>
                    <Modal.Footer>
                        <Button
                            variant="secondary"
                            onClick={() => {
                                setAddModalOpen(false);
                                setSelectedModule(null);
                            }}
                        >
                            Cancel
                        </Button>
                    </Modal.Footer>
                </Modal>
            )}

            {/* Add Notification - Step 2: Configuration */}
            {addModalOpen && selectedServiceType && (
                <Modal
                    isOpen={true}
                    onClose={() => {
                        setAddModalOpen(false);
                        setSelectedServiceType(null);
                    }}
                    size="medium"
                >
                    <Modal.Header>
                        Add {NOTIFICATIONS_SCHEMA.find(s => s.type === selectedServiceType)?.label}{' '}
                        Notification
                    </Modal.Header>
                    <Modal.Body>
                        <div className="mb-4">
                            <p className="text-sm text-fg-muted">
                                Module:{' '}
                                <span className="font-medium text-fg">{selectedModule}</span>
                            </p>
                        </div>
                        <div className="flex flex-col gap-4">
                            {NOTIFICATIONS_SCHEMA.find(
                                s => s.type === selectedServiceType
                            )?.fields.map(field => {
                                const FieldComponent = FieldRegistry.getField(field.type);
                                return (
                                    <FieldComponent
                                        key={field.key}
                                        field={field}
                                        value={formData[field.key] || ''}
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
                            variant="ghost"
                            onClick={() => setSelectedServiceType(null)}
                            disabled={isSaving}
                        >
                            Back
                        </Button>
                        <Button
                            variant="ghost"
                            bgClass="bg-transparent"
                            textClass="text-fg"
                            onClick={() => {
                                setAddModalOpen(false);
                                setSelectedServiceType(null);
                            }}
                            disabled={isSaving}
                            style={{ border: '2px solid var(--primary)' }}
                        >
                            Cancel
                        </Button>
                        <Button
                            variant="primary"
                            onClick={() => handleFormSubmit(false)}
                            disabled={isSaving}
                        >
                            {isSaving ? 'Saving...' : 'Add Notification'}
                        </Button>
                    </Modal.Footer>
                </Modal>
            )}

            {/* Edit Notification Modal */}
            {editModalOpen && selectedServiceType && (
                <Modal isOpen={true} onClose={() => setEditModalOpen(false)} size="medium">
                    <Modal.Header>
                        Edit {NOTIFICATIONS_SCHEMA.find(s => s.type === selectedServiceType)?.label}{' '}
                        Notification
                    </Modal.Header>
                    <Modal.Body>
                        <div className="mb-4">
                            <p className="text-sm text-fg-muted">
                                Module:{' '}
                                <span className="font-medium text-fg">{selectedModule}</span>
                            </p>
                            <p className="text-sm text-fg-muted">
                                Service:{' '}
                                <span className="font-medium text-fg">
                                    {
                                        NOTIFICATIONS_SCHEMA.find(
                                            s => s.type === selectedServiceType
                                        )?.label
                                    }
                                </span>
                            </p>
                        </div>
                        <div className="flex flex-col gap-4">
                            {NOTIFICATIONS_SCHEMA.find(
                                s => s.type === selectedServiceType
                            )?.fields.map(field => {
                                const FieldComponent = FieldRegistry.getField(field.type);
                                return (
                                    <FieldComponent
                                        key={field.key}
                                        field={field}
                                        value={formData[field.key] || ''}
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
                            variant="ghost"
                            bgClass="bg-transparent"
                            textClass="text-fg"
                            onClick={() => setEditModalOpen(false)}
                            disabled={isSaving}
                            style={{ border: '2px solid var(--primary)' }}
                        >
                            Cancel
                        </Button>
                        <Button
                            variant="primary"
                            onClick={() => handleEditSubmit()}
                            disabled={isSaving}
                        >
                            {isSaving ? 'Saving...' : 'Save Changes'}
                        </Button>
                    </Modal.Footer>
                </Modal>
            )}

            {/* Delete Notification Modal */}
            {deleteModalOpen && moduleToDelete && serviceToDelete && (
                <Modal isOpen={true} onClose={() => setDeleteModalOpen(false)} size="small">
                    <Modal.Header>Confirm Delete</Modal.Header>
                    <Modal.Body>
                        <div className="flex flex-col gap-4">
                            <p className="text-base">
                                Are you sure you want to delete this notification?
                            </p>
                            <div className="p-4 bg-surface-alt rounded-lg border border-border">
                                <div className="flex flex-col gap-2 text-sm">
                                    <div>
                                        <span className="text-fg-muted">Module:</span>{' '}
                                        <span className="font-medium">{moduleToDelete}</span>
                                    </div>
                                    <div>
                                        <span className="text-fg-muted">Service:</span>{' '}
                                        <span className="font-medium">
                                            {
                                                NOTIFICATIONS_SCHEMA.find(
                                                    s => s.type === serviceToDelete
                                                )?.label
                                            }
                                        </span>
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
                            {isSaving ? 'Deleting...' : 'Delete Notification'}
                        </Button>
                    </Modal.Footer>
                </Modal>
            )}

            {/* Bulk: apply one service config to multiple modules */}
            {bulkOpen && (
                <Modal isOpen={true} onClose={() => setBulkOpen(false)} size="medium">
                    <Modal.Header>Apply a notification to multiple modules</Modal.Header>
                    <Modal.Body>
                        {!bulkService ? (
                            <div className="flex flex-col gap-4">
                                <p className="text-sm text-fg-muted">
                                    Choose a service, then pick which modules it should notify.
                                </p>
                                {NOTIFICATIONS_SCHEMA.map(service => (
                                    <Button
                                        key={service.type}
                                        variant="ghost"
                                        fullWidth
                                        className="justify-start"
                                        onClick={() => {
                                            setBulkService(service.type);
                                            setBulkForm({});
                                            setBulkErrors({});
                                        }}
                                    >
                                        <div className="flex items-center gap-3 w-full">
                                            <div className="flex items-center justify-center min-w-6">
                                                <ServiceIcon service={service.type} size="medium" />
                                            </div>
                                            <div className="flex-1 text-left">
                                                <div className="font-medium">{service.label}</div>
                                            </div>
                                        </div>
                                    </Button>
                                ))}
                            </div>
                        ) : (
                            <div className="flex flex-col gap-4">
                                {NOTIFICATIONS_SCHEMA.find(s => s.type === bulkService)?.fields.map(
                                    field => {
                                        const FieldComponent = FieldRegistry.getField(field.type);
                                        return (
                                            <FieldComponent
                                                key={field.key}
                                                field={field}
                                                value={bulkForm[field.key] || ''}
                                                onChange={value =>
                                                    handleBulkFieldChange(field.key, value)
                                                }
                                                errorMessage={bulkErrors[field.key]}
                                                highlightInvalid={!!bulkErrors[field.key]}
                                            />
                                        );
                                    }
                                )}
                                <div>
                                    <div className="flex items-center justify-between mb-2">
                                        <span className="text-sm font-medium text-fg-muted">
                                            Apply to modules ({bulkModules.size})
                                        </span>
                                        <div className="flex gap-2">
                                            <Button
                                                variant="ghost"
                                                size="small"
                                                onClick={() =>
                                                    setBulkModules(new Set(NOTIFY_MODULES))
                                                }
                                            >
                                                Select all
                                            </Button>
                                            <Button
                                                variant="ghost"
                                                size="small"
                                                onClick={() => setBulkModules(new Set(['main']))}
                                            >
                                                Errors only
                                            </Button>
                                            <Button
                                                variant="ghost"
                                                size="small"
                                                onClick={() => setBulkModules(new Set())}
                                            >
                                                Clear
                                            </Button>
                                        </div>
                                    </div>
                                    <div className="grid grid-cols-2 gap-2 max-h-60 overflow-y-auto">
                                        {NOTIFY_MODULES.map(m => (
                                            <label
                                                key={m}
                                                className="flex items-center gap-2 p-2 rounded-lg bg-surface-alt cursor-pointer"
                                            >
                                                <input
                                                    type="checkbox"
                                                    checked={bulkModules.has(m)}
                                                    onChange={() => toggleBulkModule(m)}
                                                    style={{ accentColor: 'var(--primary)' }}
                                                />
                                                <span className="text-sm">
                                                    {m === 'main'
                                                        ? 'All errors (global)'
                                                        : humanize(m)}
                                                </span>
                                            </label>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        )}
                    </Modal.Body>
                    <Modal.Footer>
                        {bulkService && (
                            <Button
                                variant="ghost"
                                onClick={() => setBulkService(null)}
                                disabled={bulkSaving}
                            >
                                Back
                            </Button>
                        )}
                        <Button
                            variant="secondary"
                            onClick={() => setBulkOpen(false)}
                            disabled={bulkSaving}
                        >
                            Cancel
                        </Button>
                        {bulkService && (
                            <Button
                                variant="primary"
                                onClick={handleBulkSubmit}
                                disabled={bulkSaving || bulkModules.size === 0}
                            >
                                {bulkSaving
                                    ? 'Applying...'
                                    : `Apply to ${bulkModules.size} module${bulkModules.size === 1 ? '' : 's'}`}
                            </Button>
                        )}
                    </Modal.Footer>
                </Modal>
            )}
        </div>
    );
};
