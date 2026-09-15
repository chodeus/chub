import React, { useCallback, useMemo, useState } from 'react';
import { moduleOrder } from '../../utils/constants/constants.js';
import { CONFIG_ONLY_MODULE_KEYS } from '../../utils/constants/settings_schema.js';
import { withExtensionConfigModuleKeys } from '../../extensions/index.js';
import { humanize } from '../../utils/tools.js';
import { useModuleExecution } from '../../hooks/useModuleExecution.js';
import { useApiData } from '../../hooks/useApiData';
import { scheduleAPI } from '../../utils/api/schedule';
import { modulesAPI } from '../../utils/api/modules';
import { useToast } from '../../contexts/ToastContext';
import { PageHeader } from '../../components/ui/PageHeader';
import { Button, Modal } from '../../components/ui';
import { ScheduleCard } from '../../components/modules/ScheduleCard';
import { ScheduleField } from '../../components/fields/custom/ScheduleField';
import {
    ScheduleBlocksEditor,
    blocksFromConfig,
    blocksToConfig,
} from '../../components/modules/ScheduleBlocksEditor';

export const SchedulePage = () => {
    // Toast for notifications
    const toast = useToast();

    // Modal state
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingModule, setEditingModule] = useState(null);
    const [scheduleValue, setScheduleValue] = useState('');
    const [blockValue, setBlockValue] = useState([]);
    const [isSaving, setIsSaving] = useState(false);

    // API Data - Schedule
    const {
        data: scheduleData,
        isLoading: isLoadingSchedule,
        error: scheduleError,
        execute: refetchSchedules,
    } = useApiData({
        apiFunction: scheduleAPI.fetchSchedules,
    });

    // Module Execution Hook
    const { executeModule, isRunning, runStates } = useModuleExecution();

    const handleModuleCancel = useCallback(
        async moduleKey => {
            const jobId = runStates[moduleKey]?.job_id;
            if (!jobId) {
                toast.error(`No active job found for ${humanize(moduleKey)}`);
                return;
            }
            try {
                await modulesAPI.cancelExecution(moduleKey, jobId);
                toast.info(`Cancellation requested for ${humanize(moduleKey)}`);
            } catch (err) {
                toast.error(`Failed to cancel: ${err?.message || 'Unknown error'}`);
            }
        },
        [runStates, toast]
    );

    // Derive data
    const schedules = useMemo(
        () => scheduleData?.data?.schedule || {},
        [scheduleData?.data?.schedule]
    );
    // Per-instance sub-schedules grouped by module key (read-only display).
    const subSchedulesByModule = useMemo(() => {
        const grouped = {};
        for (const sub of scheduleData?.data?.sub_schedules || []) {
            (grouped[sub.module] ||= []).push(sub);
        }
        return grouped;
    }, [scheduleData?.data?.sub_schedules]);
    // Editable multi-block schedules keyed by module.
    const scheduleBlocksByModule = useMemo(
        () => scheduleData?.data?.schedule_blocks || {},
        [scheduleData?.data?.schedule_blocks]
    );
    // Schedulable modules: extension modules (e.g. poster_self_heal) spliced in
    // at their anchors, minus config-only modules (runnable:false, e.g.
    // cl2k_maker) which have nothing to run/schedule. Identity on main.
    const availableModules = useMemo(
        () =>
            withExtensionConfigModuleKeys(moduleOrder)
                .filter(k => k !== 'main' && k !== 'general' && !CONFIG_ONLY_MODULE_KEYS.has(k))
                .map(moduleKey => ({ key: moduleKey, label: humanize(moduleKey) })),
        []
    );

    // Handlers
    const handleModuleRun = useCallback(
        async moduleKey => {
            try {
                await executeModule(moduleKey);
            } catch (error) {
                console.error(`Failed to execute ${moduleKey}:`, error);
            }
        },
        [executeModule]
    );

    const handleScheduleEdit = useCallback(
        moduleKey => {
            const module = availableModules.find(m => m.key === moduleKey);
            if (!module) return;

            const currentSchedule = schedules[moduleKey] || '';

            // Set modal state and open
            setEditingModule(module);
            setScheduleValue(currentSchedule);
            setBlockValue(blocksFromConfig(scheduleBlocksByModule[moduleKey] || []));
            setIsModalOpen(true);
        },
        [availableModules, schedules, scheduleBlocksByModule]
    );

    const handleModalClose = useCallback(() => {
        if (isSaving) return; // Prevent closing while saving

        setIsModalOpen(false);
        setEditingModule(null);
        setScheduleValue('');
        setBlockValue([]);
        setIsSaving(false);
    }, [isSaving]);

    const handleScheduleChange = useCallback(newValue => {
        setScheduleValue(newValue);
    }, []);

    const handleSave = useCallback(async () => {
        if (!editingModule || isSaving) return;

        // Validate/serialize blocks before any write so an invalid advanced
        // JSON override aborts cleanly without a partial save.
        let payloadBlocks;
        try {
            payloadBlocks = blocksToConfig(blockValue);
        } catch (error) {
            toast.error(error.message || 'Invalid schedule block');
            return;
        }

        setIsSaving(true);

        try {
            // Call dedicated schedule API
            await scheduleAPI.updateSchedule({
                module: editingModule.key,
                schedule: scheduleValue,
            });

            // Persist the module's multi-block schedules.
            await scheduleAPI.updateScheduleBlocks({
                module: editingModule.key,
                blocks: payloadBlocks,
            });

            // Refresh schedule data (bypass cache to show updated data)
            await refetchSchedules({ useCache: false });

            // Show success toast
            toast.success(
                `Schedule ${scheduleValue ? 'updated' : 'removed'} for ${editingModule.label}`
            );

            // Close modal
            handleModalClose();
        } catch (error) {
            console.error('Failed to save schedule:', error);
            toast.error(`Failed to save schedule: ${error.message || 'Unknown error'}`);
            setIsSaving(false);
        }
    }, [
        editingModule,
        scheduleValue,
        blockValue,
        toast,
        refetchSchedules,
        handleModalClose,
        isSaving,
    ]);

    const handleRemove = useCallback(async () => {
        if (!editingModule || isSaving) return;

        setIsSaving(true);

        try {
            // Call dedicated delete endpoint
            await scheduleAPI.deleteSchedule(editingModule.key);

            // Refresh schedule data (bypass cache to show updated data)
            await refetchSchedules({ useCache: false });

            // Show success toast
            toast.success(`Schedule removed for ${editingModule.label}`);

            // Close modal
            handleModalClose();
        } catch (error) {
            console.error('Failed to remove schedule:', error);
            toast.error(`Failed to remove schedule: ${error.message || 'Unknown error'}`);
            setIsSaving(false);
        }
    }, [editingModule, toast, refetchSchedules, handleModalClose, isSaving]);

    // Loading state
    if (isLoadingSchedule) {
        return (
            <div className="flex justify-center items-center min-h-64">
                <div className="text-fg text-lg">Loading module schedules...</div>
            </div>
        );
    }

    // Error state
    if (scheduleError) {
        return (
            <div className="flex justify-center items-center min-h-64">
                <div className="text-error text-lg">
                    Error loading schedules: {scheduleError.message}
                </div>
            </div>
        );
    }

    return (
        <div className="max-w-screen-xl mx-auto flex flex-col gap-6">
            {/* Page Header */}
            <PageHeader
                title="Schedule"
                description="When each module runs — base schedule, per-instance profiles, and multi-block overrides."
            />

            {/* Module rows */}
            <div className="flex flex-col gap-3">
                {availableModules.map(module => (
                    <ScheduleCard
                        key={module.key}
                        moduleKey={module.key}
                        moduleLabel={module.label}
                        schedule={schedules[module.key]}
                        subSchedules={subSchedulesByModule[module.key]}
                        isRunning={isRunning(module.key)}
                        onRun={handleModuleRun}
                        onEdit={handleScheduleEdit}
                        onCancel={handleModuleCancel}
                    />
                ))}
            </div>

            {/* Empty State */}
            {availableModules.length === 0 && (
                <div className="text-center py-12 text-fg-muted">
                    <span className="material-symbols-outlined text-4xl mb-2 block opacity-50">
                        schedule
                    </span>
                    <p className="text-lg">No modules available for scheduling</p>
                </div>
            )}

            {/* Legend — explains base vs profile vs block schedules */}
            {availableModules.length > 0 && (
                <div className="flex items-center gap-3 rounded-xl border border-dashed border-border px-[18px] py-3.5">
                    <span className="material-symbols-outlined text-fg-subtle text-lg">info</span>
                    <span className="text-[12.5px] text-fg-subtle">
                        The base schedule runs the module across all instances.{' '}
                        <span className="text-accent">Profiles</span> fire independently per
                        instance; <span className="text-warning">blocks</span> fire on their own
                        schedule with per-run overrides. All run in addition to the base.
                    </span>
                </div>
            )}

            {/* Schedule Configuration Modal */}
            <Modal
                isOpen={isModalOpen}
                onClose={handleModalClose}
                size="medium"
                closable={!isSaving}
            >
                <Modal.Header>Configure Schedule - {editingModule?.label || 'Module'}</Modal.Header>
                <Modal.Body>
                    {editingModule && (
                        <>
                            <ScheduleField
                                field={{
                                    key: 'schedule',
                                    label: 'Schedule Configuration',
                                    description:
                                        'Configure when this module should run automatically',
                                    required: false,
                                }}
                                value={scheduleValue}
                                onChange={handleScheduleChange}
                                disabled={isSaving}
                            />
                            <ScheduleBlocksEditor
                                blocks={blockValue}
                                onChange={setBlockValue}
                                disabled={isSaving}
                            />
                        </>
                    )}
                </Modal.Body>
                <Modal.Footer>
                    <div className="flex flex-wrap justify-between items-center gap-3 w-full">
                        <Button onClick={handleRemove} variant="danger" disabled={isSaving}>
                            Remove Schedule
                        </Button>
                        <div className="flex flex-wrap gap-3">
                            <Button
                                onClick={handleModalClose}
                                variant="secondary"
                                disabled={isSaving}
                            >
                                Cancel
                            </Button>
                            <Button onClick={handleSave} variant="primary" disabled={isSaving}>
                                {isSaving ? 'Saving...' : 'Save Schedule'}
                            </Button>
                        </div>
                    </div>
                </Modal.Footer>
            </Modal>
        </div>
    );
};
