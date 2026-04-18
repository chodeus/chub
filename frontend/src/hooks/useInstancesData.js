/**
 * Instance Data Management Hook
 * Provides centralized access to instances API data with caching and helper functions
 */

import { useCallback } from 'react';
import { useApiData } from './useApiData';
import { configAPI } from '../utils/api/config';
import {
    generateInstanceOptions,
    getInstanceType as getInstanceTypeUtil,
} from '../utils/forms/conditionalFields';

/**
 * Hook for managing instance data with API integration
 * @returns {Object} Instance data and helper functions
 */
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

    /**
     * Get dropdown options for specific allowed instance types
     * @param {Array} allowedTypes - Array of allowed service types (e.g. ['radarr', 'sonarr'])
     * @returns {Array} Dropdown options array
     */
    const getInstanceOptions = useCallback(
        (allowedTypes = []) => {
            return generateInstanceOptions(instancesData, allowedTypes);
        },
        [instancesData]
    );

    /**
     * Get instance type for a specific instance name
     * @param {string} instanceName - Instance name to look up
     * @returns {string|null} Instance type (radarr, sonarr, plex) or null
     */
    const getInstanceType = useCallback(
        instanceName => {
            return getInstanceTypeUtil(instanceName, instancesData);
        },
        [instancesData]
    );

    /**
     * Check if instances data is ready for use
     * @returns {boolean} True if data is loaded and available
     */
    const isInstancesReady = useCallback(() => {
        return !isLoading && !error && !!instancesData;
    }, [isLoading, error, instancesData]);

    /**
     * Get all available service types
     * @returns {Array} Array of service type strings
     */
    const getAvailableServiceTypes = useCallback(() => {
        if (!instancesData) return [];
        return Object.keys(instancesData);
    }, [instancesData]);

    /**
     * Get instances for a specific service type
     * @param {string} serviceType - Service type (radarr, sonarr, plex)
     * @returns {Object} Instance objects for the service type
     */
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
