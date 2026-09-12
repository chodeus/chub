/**
 * NumberField Component
 *
 * Clean number input (no ± stepper buttons — those aren't in the mocks).
 * Accepts typed digits/decimal/minus; min/max bounds are applied on blur.
 */

import React, { useCallback, useState } from 'react';
import { FieldRow, InputBase } from '../primitives';

export const NumberField = React.memo(
    ({
        field,
        value,
        onChange,
        disabled = false,
        highlightInvalid = false,
        errorMessage = null,
        onBlur,
    }) => {
        // Text shown while typing; partial input ("1.", "-") stays here and is never emitted.
        const [draft, setDraft] = useState(null);
        const numValue = value !== null && value !== undefined ? Number(value) : 0;
        const min = field.min !== undefined ? Number(field.min) : undefined;
        const max = field.max !== undefined ? Number(field.max) : undefined;

        // Out-of-range text stays in the draft (the "5" of "50" with min 10), so a save
        // without blur (Ctrl/Cmd+S) sends the last in-range value.
        const handleInputChange = useCallback(
            e => {
                const inputValue = e.target.value;
                if (!/^-?\d*\.?\d*$/.test(inputValue)) return;
                setDraft(inputValue);
                if (inputValue === '') {
                    onChange(null);
                    return;
                }
                const next = Number(inputValue);
                const inRange = next >= (min ?? -Infinity) && next <= (max ?? Infinity);
                if (/^-?\d*\.?\d+$/.test(inputValue) && inRange) onChange(next);
            },
            [min, max, onChange]
        );

        const handleBlur = useCallback(
            e => {
                const typed = draft ? Number(draft) : NaN;
                if (Number.isFinite(typed)) {
                    const clamped = Math.min(max ?? Infinity, Math.max(min ?? -Infinity, typed));
                    if (clamped !== value) onChange(clamped);
                }
                setDraft(null);
                onBlur?.(e);
            },
            [draft, value, min, max, onChange, onBlur]
        );

        const inputId = field.id || `field-${field.key}`;

        return (
            <FieldRow
                htmlFor={inputId}
                label={field.label}
                required={field.required}
                description={field.description}
                error={errorMessage}
                invalid={highlightInvalid}
            >
                <InputBase
                    id={inputId}
                    type="text"
                    inputMode="numeric"
                    name={field.key}
                    value={
                        draft ??
                        (typeof value === 'string'
                            ? value
                            : Number.isFinite(numValue)
                              ? numValue
                              : '')
                    }
                    onChange={handleInputChange}
                    onBlur={handleBlur}
                    disabled={disabled}
                    required={field.required}
                    placeholder={field.placeholder}
                    invalid={highlightInvalid}
                    className="w-full sm:max-w-[200px] sm:ml-auto"
                    aria-describedby={`${field.descId || `${inputId}-desc`} ${field.errorId || `${inputId}-error`}`.trim()}
                    aria-invalid={highlightInvalid}
                />
            </FieldRow>
        );
    }
);

NumberField.displayName = 'NumberField';
