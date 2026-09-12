/**
 * FloatField Component
 *
 * Percentage input field with +/- buttons using primitive composition.
 * Displays percentages (0-100%) but stores as decimal (0-1).
 */

import React, { useCallback, useState } from 'react';
import { FieldRow, InputBase } from '../primitives';
import { FieldButton } from '../features/shared';

const toStored = percent => Math.round((percent / 100) * 1000) / 1000;

export const FloatField = React.memo(
    ({
        field,
        value,
        onChange,
        disabled = false,
        highlightInvalid = false,
        errorMessage = null,
    }) => {
        // Text shown while typing; partial input ("1.", "-") stays here and is never emitted.
        const [draft, setDraft] = useState(null);
        // Convert decimal (0-1) to percentage (0-100) for display with precision fix
        const percentageValue =
            value !== null && value !== undefined
                ? Math.round(Number(value) * 100 * 1000) / 1000 // Round to 3 decimal places to avoid floating-point errors
                : 0;
        const step = field.step || 1;
        const percentMin = field.min !== undefined ? Number(field.min) : 0;
        const percentMax = field.max !== undefined ? Number(field.max) : 100;

        const handleInputChange = useCallback(
            e => {
                const inputValue = e.target.value;
                if (!/^-?\d*\.?\d*$/.test(inputValue)) return;
                if (!/^-?\d*\.?\d+$/.test(inputValue)) {
                    setDraft(inputValue);
                    if (inputValue === '') onChange(null);
                    return;
                }
                const newPercentValue = Number(inputValue);
                if (newPercentValue < percentMin || newPercentValue > percentMax) return;
                setDraft(inputValue);
                onChange(toStored(newPercentValue));
            },
            [percentMin, percentMax, onChange]
        );

        const handleDecrement = useCallback(() => {
            const newPercentValue = percentageValue - step;
            if (newPercentValue < percentMin) return;
            setDraft(null);
            onChange(toStored(newPercentValue));
        }, [percentageValue, step, percentMin, onChange]);

        const handleIncrement = useCallback(() => {
            const newPercentValue = percentageValue + step;
            if (newPercentValue > percentMax) return;
            setDraft(null);
            onChange(toStored(newPercentValue));
        }, [percentageValue, step, percentMax, onChange]);

        const inputId = field.id || `field-${field.key}`;
        const decrementDisabled = disabled || percentageValue <= percentMin;
        const incrementDisabled = disabled || percentageValue >= percentMax;

        return (
            <FieldRow
                htmlFor={inputId}
                label={field.label}
                required={field.required}
                description={field.description}
                error={errorMessage}
                invalid={highlightInvalid}
            >
                <div className="flex">
                    <FieldButton
                        onClick={handleDecrement}
                        disabled={decrementDisabled}
                        ariaLabel={`Decrease ${field.label}`}
                        className="text-brand-primary"
                    >
                        <span className="material-symbols-outlined text-lg">remove</span>
                    </FieldButton>

                    <InputBase
                        id={inputId}
                        type="text"
                        name={field.key}
                        value={
                            draft ?? (value === null || value === undefined ? '' : percentageValue)
                        }
                        onChange={handleInputChange}
                        onBlur={() => setDraft(null)}
                        disabled={disabled}
                        required={field.required}
                        placeholder={field.placeholder}
                        invalid={highlightInvalid}
                        className="flex-1 border-t border-b border-default bg-input text-center"
                        aria-describedby={`${field.descId || `${inputId}-desc`} ${field.errorId || `${inputId}-error`}`.trim()}
                        aria-invalid={highlightInvalid}
                    />

                    <FieldButton
                        onClick={handleIncrement}
                        disabled={incrementDisabled}
                        ariaLabel={`Increase ${field.label}`}
                        className="text-brand-primary"
                    >
                        <span className="material-symbols-outlined text-lg">add</span>
                    </FieldButton>
                </div>
            </FieldRow>
        );
    }
);

FloatField.displayName = 'FloatField';
