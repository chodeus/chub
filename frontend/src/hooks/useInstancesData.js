import { useCallback } from 'react';
import { useApiData } from './useApiData';
import { configAPI } from '../utils/api/config';
import {
    generateInstanceOptions,
    getInstanceType as getInstanceTypeUtil,
} from '../utils/forms/conditionalFields';

/** Instances API data plus lookup helpers. */
export const useInstancesData = () => {
    const {
        data: instancesResponse,
        isLoading,
        error,
    } = useApiData({
        apiFunction: () => configAPI.fetchSection('instances'),
        options: {
            retryAttempts: 2,
            cacheKey: 'instances_data',
            cacheTTL: 300000, // 5 minutes
            showErrorToast: true,
            successMessage: null, // Don't show success toast for background data loading
        },
    });

    // Extract instances data from API response - config API nests it under data.instances
    const instancesData = instancesResponse?.data?.instances;

    /** Dropdown options, optionally narrowed to the given service types. */
    const getInstanceOptions = useCallback(
        (allowedTypes = []) => {
            return generateInstanceOptions(instancesData, allowedTypes);
        },
        [instancesData]
    );

    /** Service type for an instance name, or null. */
    const getInstanceType = useCallback(
        instanceName => {
            return getInstanceTypeUtil(instanceName, instancesData);
        },
        [instancesData]
    );

    /** True once the data has loaded without error. */
    const isInstancesReady = useCallback(() => {
        return !isLoading && !error && !!instancesData;
    }, [isLoading, error, instancesData]);

    /** The service types present in the data. */
    const getAvailableServiceTypes = useCallback(() => {
        if (!instancesData) return [];
        return Object.keys(instancesData);
    }, [instancesData]);

    /** Instances for one service type, or {}. */
    const getInstancesForServiceType = useCallback(
        serviceType => {
            if (!instancesData || !serviceType) return {};
            return instancesData[serviceType] || {};
        },
        [instancesData]
    );

    return {
        // Raw data
        instancesData,
        isLoading,
        error,

        // Helper functions
        getInstanceOptions,
        getInstanceType,
        isInstancesReady,
        getAvailableServiceTypes,
        getInstancesForServiceType,
    };
};
