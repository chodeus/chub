/**
 * PrimarySourceField Component
 *
 * A single-select dropdown that presents a "primary source" choice but
 * reads/writes the backend's ORDERED list value (List[str], first = priority).
 * With two sources (e.g. local / tmdb) and "first match wins", choosing a
 * primary emits `[primary, ...remaining]` so the other source(s) remain as
 * fallbacks in order. Loading derives the selected primary from value[0].
 *
 * Replaces the chip/priority picker for asset_renamerr's `sources` field.
 */

import React, { useCallback, useMemo } from 'react';
import { FieldWrapper, FieldLabel, FieldError, FieldDescription, SelectBase } from '../primitives';

export const PrimarySourceField = React.memo(
    ({
        field,
        value,
        onChange,
        disabled = false,
        highlightInvalid = false,
        errorMessage = null,
    }) => {
        const inputId = field.id || `field-${field.key}`;

        const options = useMemo(
            () =>
                (field.options || []).map(option =>
                    typeof option === 'string'
                        ? { value: option, label: option }
                        : { value: option.value, label: option.label || option.value }
                ),
            [field.options]
        );

        const allValues = useMemo(() => options.map(o => o.value), [options]);

        // value is an ordered list; the primary is the first known option in it.
        const current = Array.isArray(value) ? value : [];
        const primary =
            current.find(v => allValues.includes(v)) || (options[0] && options[0].value) || '';

        const handleChange = useCallback(
            e => {
                const chosen = e.target.value;
                // Emit an ordered list: chosen first, then the remaining known
                // sources (fallbacks) in their declared order.
                onChange([chosen, ...allValues.filter(v => v !== chosen)]);
            },
            [onChange, allValues]
        );

        return (
            <FieldWrapper invalid={highlightInvalid}>
                <FieldLabel htmlFor={inputId} label={field.label} required={field.required} />

                <SelectBase
                    id={inputId}
                    name={field.key}
                    value={primary}
                    onChange={handleChange}
                    disabled={disabled}
                    required={field.required}
                    invalid={highlightInvalid}
                    options={options}
                    placeholder={field.placeholder || 'Select a primary source...'}
                    ariaDescribedby={`${inputId}-desc ${inputId}-error`.trim()}
                />

                <FieldDescription id={`${inputId}-desc`} description={field.description} />
                <FieldError id={`${inputId}-error`} message={errorMessage} />
            </FieldWrapper>
        );
    }
);

PrimarySourceField.displayName = 'PrimarySourceField';
