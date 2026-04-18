import { useState, useCallback, useEffect, useRef } from 'react';
import { useToast } from '../contexts/ToastContext.jsx';
import { modulesAPI } from '../utils/api/modules.js';

/**
 * Module execution hook for running and monitoring CHUB modules
 *
 * Features:
 * - Execute modules with loading state management
 * - Real-time status polling for running modules
 * - Automatic polling start/stop based on activity
 * - Exponential backoff on consecutive errors
 * - Toast notifications for all operations
 *
 * @returns {Object} Module execution state and actions
 */
export const useModuleExecution = () => {
    const [runningModules, setRunningModules] = useState(new Set());
    const [runStates, setRunStates] = useState({});
    const [polling, setPolling] = useState(false);

    const toast = useToast();
    const pollingIntervalRef = useRef(null);
    const isMountedRef = useRef(true);
    const consecutiveErrorsRef = useRef(0);
    const currentIntervalRef = useRef(2000);
    const loadRunStatesRef = useRef(null);
    const runningModulesRef = useRef(runningModules);

    const BASE_INTERVAL = 2000;
    const MAX_INTERVAL = 30000;

    /**
     * Restart polling with a new interval (ref-stable, no hook deps)
     */
    const restartPollingWithInterval = useCallback(interval => {
        currentIntervalRef.current = interval;
        if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current);
            pollingIntervalRef.current = setInterval(() => {
                if (isMountedRef.current && loadRunStatesRef.current) {
                    loadRunStatesRef.current();
                }
            }, interval);
        }
    }, []);

    /**
     * Load run states from API with error backoff
     */
    const loadRunStates = useCallback(async () => {
        try {
            const data = await modulesAPI.fetchRunStates({ useCache: false });

            if (isMountedRef.current) {
                const newStates = data?.data || {};
                setRunStates(newStates);

                // Detect modules that finished running
                const currentRunning = runningModulesRef.current;
                if (currentRunning.size > 0) {
                    const finished = [];
                    for (const modKey of currentRunning) {
                        const modState = newStates[modKey];
                        if (!modState || modState.status !== 'running') {
                            finished.push(modKey);
                            if (modState?.status === 'success') {
                                toast.success(`${modKey} completed successfully`);
                            } else if (modState?.status === 'error') {
                                toast.error(`${modKey} failed`);
                            }
                        }
                    }
                    if (finished.length > 0) {
                        setRunningModules(prev => {
                            const newSet = new Set(prev);
                            finished.forEach(k => newSet.delete(k));
                            return newSet;
                        });
                    }
                }

                // Reset backoff on success
                if (consecutiveErrorsRef.current > 0) {
                    consecutiveErrorsRef.current = 0;
                    restartPollingWithInterval(BASE_INTERVAL);
                }
            }
        } catch (error) {
            if (isMountedRef.current) {
                consecutiveErrorsRef.current += 1;
                // Exponential backoff: 2s, 4s, 8s, 16s, 30s max
                const newInterval = Math.min(
                    BASE_INTERVAL * Math.pow(2, consecutiveErrorsRef.current),
                    MAX_INTERVAL
                );
                if (newInterval !== currentIntervalRef.current) {
                    restartPollingWithInterval(newInterval);
                }
            }
            console.error('Failed to load run states:', error);
        }
    }, [restartPollingWithInterval, toast]);

    // Keep refs in sync for interval callbacks
    loadRunStatesRef.current = loadRunStates;
    runningModulesRef.current = runningModules;

    /**
     * Start polling for status updates
     */
    const startPolling = useCallback(() => {
        if (pollingIntervalRef.current) return;

        setPolling(true);
        consecutiveErrorsRef.current = 0;
        currentIntervalRef.current = BASE_INTERVAL;
        pollingIntervalRef.current = setInterval(() => {
            if (isMountedRef.current && loadRunStatesRef.current) {
                loadRunStatesRef.current();
            }
        }, BASE_INTERVAL);
    }, []);

    /**
     * Stop polling
     */
    const stopPolling = useCallback(() => {
        if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current);
            pollingIntervalRef.current = null;
        }
        setPolling(false);
        consecutiveErrorsRef.current = 0;
        currentIntervalRef.current = BASE_INTERVAL;
    }, []);

    /**
     * Execute module
     * @param {string} moduleKey - Module key to execute
     */
    const executeModule = useCallback(
        async moduleKey => {
            try {
                setRunningModules(prev => new Set([...prev, moduleKey]));
                startPolling();

                toast.info(`Starting ${moduleKey}...`);

                const result = await modulesAPI.runModule(moduleKey);

                if (!result.success) {
                    toast.error(`${moduleKey} failed: ${result.message || 'Unknown error'}`);
                    setRunningModules(prev => {
                        const newSet = new Set(prev);
                        newSet.delete(moduleKey);
                        return newSet;
                    });
                }
                // On success, module stays in runningModules — polling will detect completion
            } catch (error) {
                console.error(`Failed to run ${moduleKey}:`, error);
                toast.error(`Failed to run ${moduleKey}: ${error.message}`);
                if (isMountedRef.current) {
                    setRunningModules(prev => {
                        const newSet = new Set(prev);
                        newSet.delete(moduleKey);
                        return newSet;
                    });
                }
            }
        },
        [toast, startPolling]
    );

    // Initial load and cleanup
    useEffect(() => {
        loadRunStates();
        return () => {
            isMountedRef.current = false;
            stopPolling();
        };
    }, [loadRunStates, stopPolling]);

    // Auto start/stop polling based on running modules
    useEffect(() => {
        if (runningModules.size > 0) {
            startPolling();
        } else {
            stopPolling();
        }
    }, [runningModules.size, startPolling, stopPolling]);

    return {
        runningModules,
        runStates,
        polling,
        executeModule,
        refreshData: loadRunStates,
        isRunning: moduleKey => runningModules.has(moduleKey),
        getRunState: moduleKey => runStates[moduleKey] || null,
    };
};
