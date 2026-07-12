/**
 * CheckboxField Component
 *
 * Boolean setting rendered as the redesign's row: label + description on the
 * left, a brand toggle on the right. Used app-wide for every boolean config.
 */

import React from 'react';
import { FieldWrapper, FieldLabel, FieldError, FieldDescription } from '../primitives';
import Toggle from '../../ui/Toggle.jsx';

/**
 * @param {Object} props.field - Field configuration object
 * @param {boolean} props.value - Current field value
 * @param {Function} props.onChange - Value change handler
 * @param {boolean} props.disabled - Field disabled state
 * @param {boolean} props.highlightInvalid - Show validation error state
 * @param {string} props.errorMessage - Error message to display
 */
export const CheckboxField = React.memo(
    ({
        field,
        value,
        onChange,
        disabled = false,
        highlightInvalid = false,
        errorMessage = null,
    }) => {
        const inputId = field.id || `field-${field.key}`;
        const isChecked = Boolean(value);

        return (
            <FieldWrapper invalid={highlightInvalid} variant="minimal">
                <div className="flex items-center justify-between gap-4 py-2">
                    <div className="min-w-0">
                        <FieldLabel
                            htmlFor={inputId}
                            label={field.label}
                            required={field.required}
                            helpText={field.helpText}
                            className="text-sm font-medium leading-normal text-fg select-none"
                        />
                        {field.description && (
                            <FieldDescription
                                id={field.descId || `${inputId}-desc`}
                                description={field.description}
                            />
                        )}
                    </div>
                    <Toggle
                        label={field.label}
                        checked={isChecked}
                        disabled={disabled}
                        onChange={next => !disabled && onChange(next)}
                    />
                </div>

                {errorMessage && (
                    <FieldError id={field.errorId || `${inputId}-error`} message={errorMessage} />
                )}
            </FieldWrapper>
        );
    }
);

CheckboxField.displayName = 'CheckboxField';

export default CheckboxField;
