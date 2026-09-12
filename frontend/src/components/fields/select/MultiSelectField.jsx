/**
 * MultiSelectField Component
 *
 * A dropdown-driven multi-select that maintains an ORDERED list value
 * (List[str], order = priority). Selected entries render as removable,
 * numbered chips above an "add" dropdown of the not-yet-selected options.
 * Selecting from the dropdown appends to the end (lowest priority); removing
 * a chip drops it. Used for asset_renamerr's `tmdb_language` (preferred
 * languages, first = highest priority).
 */

import React, { useCallback, useMemo } from 'react';
import { FieldWrapper, FieldLabel, FieldError, FieldDescription, SelectBase } from '../primitives';

export const MultiSelectField = React.memo(
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

        const labelFor = useCallback(
            v => {
                const o = options.find(x => x.value === v);
                return o ? o.label : v;
            },
            [options]
        );

        const selected = useMemo(() => (Array.isArray(value) ? value : []), [value]);
        const available = useMemo(
            () => options.filter(o => !selected.includes(o.value)),
            [options, selected]
        );

        const addValue = useCallback(
            e => {
                const v = e.target.value;
                if (v && !selected.includes(v)) onChange([...selected, v]);
            },
            [onChange, selected]
        );

        const removeValue = useCallback(
            v => onChange(selected.filter(x => x !== v)),
            [onChange, selected]
        );

        return (
            <FieldWrapper invalid={highlightInvalid}>
                <FieldLabel htmlFor={inputId} label={field.label} required={field.required} />

                {/* The × is a real 36px box, not a touch-expand: an expanded hit area
                    on a 26px chip reached across the row gap into the next chip's ×. */}
                {selected.length > 0 && (
                    <div className="flex flex-wrap gap-2 mb-2">
                        {selected.map((v, i) => (
                            <span
                                key={v}
                                className="inline-flex items-center gap-1 min-h-11 px-2 rounded-md bg-primary/20 text-fg text-sm"
                            >
                                <span className="text-xs text-fg-subtle">{i + 1}.</span>
                                {labelFor(v)}
                                {!disabled && (
                                    <button
                                        type="button"
                                        onClick={() => removeValue(v)}
                                        aria-label={`Remove ${labelFor(v)}`}
                                        className="ml-1 inline-flex items-center justify-center w-9 h-9 shrink-0 leading-none hover:text-error"
                                    >
                                        ×
                                    </button>
                                )}
                            </span>
                        ))}
                    </div>
                )}

                <SelectBase
                    id={inputId}
                    name={field.key}
                    value=""
                    onChange={addValue}
                    disabled={disabled || available.length === 0}
                    invalid={highlightInvalid}
                    options={available}
                    placeholder={
                        available.length ? field.placeholder || 'Add…' : 'All options added'
                    }
                    ariaDescribedby={`${inputId}-desc ${inputId}-error`.trim()}
                />

                <FieldDescription id={`${inputId}-desc`} description={field.description} />
                <FieldError id={`${inputId}-error`} message={errorMessage} />
            </FieldWrapper>
        );
    }
);

MultiSelectField.displayName = 'MultiSelectField';
