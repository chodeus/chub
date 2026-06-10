/**
 * PresetsField Component - Unified schema-driven preset selector
 *
 * Replaces HolidayPresetsField and GDrivePresetsField with a single
 * configurable component that uses schema to determine behavior.
 */

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { FieldWrapper, FieldLabel, FieldError, FieldDescription, SelectBase } from '../primitives';
import { Card } from '../../ui';
import { borderReplacerrAPI } from '../../../utils/api/border_replacerr.js';
import { fetchGdrivePresets } from '../../../utils/gdrivePresets.js';

// In-memory cache so opening the holiday picker multiple times in one
// session doesn't re-hit the backend. The catalogue is static between
// deploys.
let _holidayPresetsCache = null;

/**
 * PresetsField component for schema-driven preset selection
 *
 * @param {Object} props - Component props
 * @param {Object} props.field - Field configuration object with preset schema
 * @param {string} props.value - Current field value
 * @param {Function} props.onChange - Value change handler
 * @param {boolean} props.disabled - Field disabled state
 * @param {boolean} props.highlightInvalid - Show validation error state
 * @param {string} props.errorMessage - Error message to display
 * @param {Function} props.onPresetSelected - Callback when preset is selected
 * @param {Object} props.moduleConfig - Module configuration for tracking already added presets
 */
export const PresetsField = React.memo(
    ({
        field,
        value,
        onChange,
        disabled = false,
        highlightInvalid = false,
        errorMessage = null,
        onPresetSelected,
        moduleConfig = {},
    }) => {
        const [presets, setPresets] = useState([]);
        const [loading, setLoading] = useState(false);

        // Extract preset configuration from field schema
        const presetType = field.presetType || 'holiday'; // Default to holiday
        const presetUrl = field.presetUrl;
        const presetData = field.presetData;
        const targetFields = useMemo(() => field.targetFields || [], [field.targetFields]);
        const identifierField = field.identifierField || 'name'; // Field used to identify presets
        const moduleConfigKey = field.moduleConfigKey; // Key in moduleConfig to check for duplicates

        // Load presets based on configuration
        useEffect(() => {
            let mounted = true;

            if (presetType === 'holiday') {
                // Backend is source of truth (GET /border-replacerr/presets).
                if (_holidayPresetsCache) {
                    setPresets(_holidayPresetsCache);
                    return;
                }
                setLoading(true);
                borderReplacerrAPI
                    .fetchPresets()
                    .then(resp => {
                        const list = resp?.data?.presets;
                        if (Array.isArray(list)) {
                            _holidayPresetsCache = list;
                            if (mounted) setPresets(list);
                        }
                    })
                    .catch(() => mounted && setPresets([]))
                    .finally(() => mounted && setLoading(false));
                return () => {
                    mounted = false;
                };
            }

            if (presetType === 'gdrive' && presetUrl) {
                // Fetch GDrive presets (shared helper handles internal/external
                // payload shapes + upstream fallback).
                setLoading(true);
                fetchGdrivePresets(presetUrl)
                    .then(arr => mounted && setPresets(arr))
                    .finally(() => mounted && setLoading(false));

                return () => {
                    mounted = false;
                };
            }

            if (presetData) {
                // Use provided preset data
                setPresets(presetData);
            }
        }, [presetType, presetUrl, presetData]);

        // Extract already used preset identifiers from moduleConfig.
        // Tracks both name (identifierField) and id, since users sometimes
        // rename entries after adding them — id-matching keeps the
        // duplicate guard accurate even when display names diverge.
        const alreadyAdded = useMemo(() => {
            if (moduleConfigKey && Array.isArray(moduleConfig?.[moduleConfigKey])) {
                const entries = moduleConfig[moduleConfigKey];
                return {
                    names: new Set(entries.map(e => e?.[identifierField]).filter(Boolean)),
                    ids: new Set(entries.map(e => e?.id).filter(Boolean)),
                };
            }
            return { names: new Set(), ids: new Set() };
        }, [moduleConfig, moduleConfigKey, identifierField]);

        // Transform presets to SelectBase options format. The currently-
        // selected option stays enabled so the user can see what was picked.
        const options = useMemo(() => {
            const baseOptions = [{ value: '', label: '— Select preset... —' }];

            const presetOptions = presets.map(preset => {
                const identifier = preset[identifierField];
                const isCurrentSelection = identifier === value;
                const dupByName = alreadyAdded.names.has(identifier);
                const dupById = preset.id && alreadyAdded.ids.has(preset.id);
                const isDuplicate = !isCurrentSelection && (dupByName || dupById);
                return {
                    value: identifier,
                    label: preset.name + (isDuplicate ? ' (Already Added)' : ''),
                    disabled: isDuplicate,
                };
            });

            return [...baseOptions, ...presetOptions];
        }, [presets, alreadyAdded, identifierField, value]);

        const handleChange = useCallback(
            e => {
                const selectedValue = e.target.value;

                onChange(selectedValue);

                if (onPresetSelected && selectedValue) {
                    const selectedPreset = presets.find(p => p[identifierField] === selectedValue);

                    if (selectedPreset && targetFields.length > 0) {
                        // Build preset data mapping based on targetFields configuration
                        const presetFieldUpdates = {};

                        // Map preset data to target field names
                        targetFields.forEach(targetField => {
                            if (Object.hasOwn(selectedPreset, targetField)) {
                                presetFieldUpdates[targetField] = selectedPreset[targetField];
                            }
                        });

                        // Always include the current field's value
                        presetFieldUpdates[field.key] = selectedValue;

                        onPresetSelected(presetFieldUpdates);
                    }
                }
            },
            [onChange, onPresetSelected, presets, field.key, identifierField, targetFields]
        );

        const inputId = `field-${field.key}`;
        const inputValue = value || '';

        // Find selected preset for detail display
        const selectedPreset = presets.find(p => p[identifierField] === value);

        return (
            <FieldWrapper invalid={highlightInvalid} variant="form-section">
                <FieldLabel
                    htmlFor={inputId}
                    label={field.label || `${presetType} Presets`}
                    required={field.required}
                />

                <SelectBase
                    id={inputId}
                    name={field.key}
                    value={inputValue}
                    onChange={handleChange}
                    disabled={disabled || loading}
                    required={field.required}
                    invalid={highlightInvalid}
                    options={options}
                    ariaDescribedby={`${inputId}-desc ${inputId}-error`.trim()}
                />

                <FieldDescription id={`${inputId}-desc`} description={field.description} />
                <FieldError id={`${inputId}-error`} message={errorMessage} />

                {/* Preset Details Card - Only show for gdrive presets */}
                {selectedPreset && presetType === 'gdrive' && (
                    <Card
                        data={selectedPreset}
                        excludeKeys={[identifierField === 'id' ? 'id' : '']}
                        title={`${presetType} Preset Details`}
                    />
                )}
            </FieldWrapper>
        );
    }
);

PresetsField.displayName = 'PresetsField';
