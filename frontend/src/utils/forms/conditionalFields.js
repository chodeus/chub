/**
 * Conditional Field Utilities
 * Provides evaluation functions for schema-driven conditional field rendering
 */

/**
 * Supported condition types for field evaluation
 */
const CONDITION_TYPES = {
    instance_type_equals: (selectedValue, targetValue, apiData) => {
        const instanceType = getInstanceType(selectedValue, apiData);
        return instanceType === targetValue;
    },
    instance_type_in: (selectedValue, targetValues, apiData) => {
        const instanceType = getInstanceType(selectedValue, apiData);
        return Array.isArray(targetValues) && targetValues.includes(instanceType);
    },
    equals: (selectedValue, targetValue) => {
        return selectedValue === targetValue;
    },
    not_equals: (selectedValue, targetValue) => {
        return selectedValue !== targetValue;
    },
    in: (selectedValue, targetValues) => {
        return Array.isArray(targetValues) && targetValues.includes(selectedValue);
    },
    not_in: (selectedValue, targetValues) => {
        return Array.isArray(targetValues) && !targetValues.includes(selectedValue);
    },
    is_empty: selectedValue =>
        selectedValue === undefined ||
        selectedValue === null ||
        selectedValue === '' ||
        (Array.isArray(selectedValue) && selectedValue.length === 0),
    is_not_empty: selectedValue =>
        selectedValue !== undefined &&
        selectedValue !== null &&
        selectedValue !== '' &&
        !(Array.isArray(selectedValue) && selectedValue.length === 0),
    // True when EVERY named field is empty. `value` is a list of field keys, so
    // a notice can depend on more than one field — the single-`field` form above
    // can't express "neither auth method is configured".
    all_empty: (_selectedValue, fieldNames, _apiData, formData) =>
        Array.isArray(fieldNames) &&
        fieldNames.length > 0 &&
        fieldNames.every(name => CONDITION_TYPES.is_empty(formData?.[name])),
    // True when at least one instance of the given service type is configured.
    // `apiData` is the instances dict (via api_lookup: 'instances'); `value` is
    // the service type, e.g. 'lidarr'. Used to reveal music-only options only
    // when a Lidarr instance exists, independent of any selected-instance field.
    service_configured: (selectedValue, serviceType, apiData) => {
        const instances = apiData && apiData[serviceType];
        return Boolean(instances && Object.keys(instances).length > 0);
    },
};

/**
 * Evaluate if a field should be visible based on conditional schema
 * @param {Object} field - Field schema with conditional properties
 * @param {Object} formData - Current form data values
 * @param {Object} apiData - API data for lookups (instances, etc.)
 * @returns {boolean} - Whether field should be shown
 */
export const shouldShowField = (field, formData, apiData = {}) => {
    // Handle new conditional format
    if (field.conditional) {
        const { field: dependentField, condition, value, api_lookup } = field.conditional;
        const selectedValue = formData[dependentField];
        const lookupData = api_lookup ? apiData[api_lookup] : null;

        const evaluator = CONDITION_TYPES[condition];
        if (evaluator) {
            // formData is 4th so the existing 3-arg evaluators are unaffected.
            return evaluator(selectedValue, value, lookupData, formData);
        } else {
            console.warn('[conditionalFields] Unknown condition type:', condition);
            return true;
        }
    }

    // Handle legacy format for backward compatibility
    if (field.show_if_instance_type) {
        const instanceField = field.instance_field || 'instance';
        const selectedInstance = formData[instanceField];
        const instanceType = getInstanceType(selectedInstance, apiData.instances);

        return instanceType === field.show_if_instance_type;
    }

    // Show by default if no conditions
    return true;
};

/**
 * Resolve instance-type-aware labels/description on a field.
 *
 * A field may declare per-instance-type display overrides so one shared
 * setting can speak the right vocabulary (e.g. Sonarr "Series/Season" vs
 * Lidarr "Artist/Album") while its stored values stay constant:
 *   - option.labelByType[type] overrides that option's display label
 *   - field.descriptionByType[type] overrides the field description
 * Both maps support a 'default' key used when no type matches. Returns the
 * field unchanged when it declares no such overrides (cheap no-op).
 *
 * @param {Object} field - Field schema, possibly with *ByType overrides
 * @param {string|null} instanceType - Resolved service type (sonarr, lidarr, …)
 * @returns {Object} - Field with display strings resolved for instanceType
 */
export const resolveTypeAwareField = (field, instanceType) => {
    const hasOptionLabels = Array.isArray(field.options)
        ? field.options.some(opt => opt && typeof opt === 'object' && opt.labelByType)
        : false;
    if (!field.descriptionByType && !hasOptionLabels) {
        return field;
    }

    const pick = map => (instanceType && map[instanceType]) ?? map.default;

    const resolved = { ...field };

    if (field.descriptionByType) {
        resolved.description = pick(field.descriptionByType) ?? field.description;
    }

    if (hasOptionLabels) {
        resolved.options = field.options.map(opt => {
            if (!opt || typeof opt !== 'object' || !opt.labelByType) {
                return opt;
            }
            const { labelByType, ...rest } = opt;
            return { ...rest, label: pick(labelByType) ?? rest.label ?? rest.value };
        });
    }

    return resolved;
};

/**
 * Get instance type from instance name using API data
 * @param {string} instanceName - Selected instance name
 * @param {Object} instancesData - API response data structure
 * @returns {string|null} - Instance type (radarr, sonarr, plex) or null
 */
export const getInstanceType = (instanceName, instancesData) => {
    if (!instanceName || !instancesData) {
        return null;
    }

    for (const [serviceType, instances] of Object.entries(instancesData)) {
        if (instances && typeof instances === 'object') {
            if (Object.hasOwn(instances, instanceName)) {
                return serviceType;
            }
        }
    }

    return null;
};

/**
 * Generate dropdown options from instances API data
 * @param {Object} instancesData - API response data
 * @param {Array} allowedTypes - Array of allowed service types
 * @param {boolean} includePlaceholder - Whether to include placeholder as first option (default: true for backwards compatibility)
 * @returns {Array} - Dropdown options array
 */
export const generateInstanceOptions = (
    instancesData,
    allowedTypes = [],
    includePlaceholder = true
) => {
    const options = includePlaceholder ? [{ value: '', label: '— Select instance... —' }] : [];

    if (!instancesData) {
        return options;
    }

    allowedTypes.forEach(serviceType => {
        const serviceInstances = instancesData[serviceType] || {};
        const instanceNames = Object.keys(serviceInstances);

        instanceNames.forEach(instanceName => {
            // Remove service type prefix and enhance humanization
            const cleanInstanceName = removeServicePrefix(instanceName, serviceType);
            const humanizedInstanceName = enhancedHumanize(cleanInstanceName);
            const humanizedServiceType = humanize(serviceType);

            // Avoid "Radarr Radarr" when the instance name matches the service type
            const label =
                humanizedInstanceName.toLowerCase() === humanizedServiceType.toLowerCase()
                    ? humanizedServiceType
                    : `${humanizedServiceType} ${humanizedInstanceName}`;

            options.push({
                value: instanceName,
                label,
                instanceType: serviceType,
                serviceType: serviceType,
            });
        });
    });

    return options;
};

/**
 * Humanize service type names for display
 * @param {string} text - Text to humanize
 * @returns {string} - Humanized text
 */
export const humanize = text => {
    if (!text) return '';
    return text.charAt(0).toUpperCase() + text.slice(1);
};

/**
 * Remove service type prefix from instance name to eliminate redundancy
 * @param {string} instanceName - Original instance name
 * @param {string} serviceType - Service type (radarr, sonarr, plex)
 * @returns {string} - Instance name with service prefix removed
 */
export const removeServicePrefix = (instanceName, serviceType) => {
    if (!instanceName || !serviceType) return instanceName || '';

    const lowerInstanceName = instanceName.toLowerCase();
    const lowerServiceType = serviceType.toLowerCase();

    // Check if instance name starts with service type
    if (lowerInstanceName.startsWith(lowerServiceType)) {
        // Remove the prefix and any following underscore or dash
        let cleaned = instanceName.substring(serviceType.length);

        // Remove leading separators (underscore, dash, or space)
        cleaned = cleaned.replace(/^[_\-\s]+/, '');

        // If nothing remains after removing prefix, return original name
        return cleaned || instanceName;
    }

    return instanceName;
};

/**
 * Enhanced humanization with better formatting rules
 * @param {string} text - Text to humanize
 * @returns {string} - Enhanced humanized text
 */
export const enhancedHumanize = text => {
    if (!text) return '';

    // Handle common patterns
    let result = text;

    // Replace underscores with spaces
    result = result.replace(/_/g, ' ');

    // Replace dashes with spaces
    result = result.replace(/-/g, ' ');

    // Split into words and process each
    const words = result.split(/\s+/).filter(word => word.length > 0);

    return words
        .map(word => {
            const lowerWord = word.toLowerCase();

            // Special case handling
            switch (lowerWord) {
                case '4k':
                    return '4K';
                case 'hd':
                    return 'HD';
                case 'anime':
                    return 'Anime';
                case 'test':
                    return 'Test';
                default:
                    // Standard capitalization
                    return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
            }
        })
        .join(' ');
};
