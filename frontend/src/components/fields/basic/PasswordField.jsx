import React, { useState, useCallback } from 'react';
import { FieldRow, InputBase } from '../primitives';
import { FieldButton } from '../features/shared';
import { useOptionalFormField } from '../../forms/FormContext';

export const PasswordField = React.memo(
    ({
        field,
        value,
        onChange,
        disabled = false,
        highlightInvalid = false,
        errorMessage = null,
        onBlur,
    }) => {
        // Optional FormContext integration
        const formField = useOptionalFormField(field.key);

        // Use FormContext if available, otherwise use props
        const finalValue = formField?.value ?? value;
        const finalOnChange = formField?.onChange ?? onChange;
        const finalHighlightInvalid = formField?.highlightInvalid ?? highlightInvalid;
        const finalErrorMessage = formField?.errorMessage ?? errorMessage;
        const finalOnBlur = formField?.onBlur ?? onBlur;

        const [showPassword, setShowPassword] = useState(false);

        const handleChange = useCallback(
            e => {
                finalOnChange(e.target.value);
            },
            [finalOnChange]
        );

        const togglePasswordVisibility = useCallback(() => {
            setShowPassword(prev => !prev);
        }, []);

        const inputId = field.id || `field-${field.key}`;
        const inputValue = finalValue || '';

        return (
            <FieldRow
                htmlFor={inputId}
                label={field.label}
                required={field.required}
                description={field.description}
                error={finalErrorMessage}
                invalid={finalHighlightInvalid}
            >
                <div className="flex">
                    <InputBase
                        id={inputId}
                        type={showPassword ? 'text' : 'password'}
                        name={field.key}
                        value={inputValue}
                        placeholder={field.placeholder}
                        disabled={disabled}
                        required={field.required}
                        maxLength={field.maxLength}
                        minLength={field.minLength}
                        onChange={handleChange}
                        onBlur={finalOnBlur}
                        invalid={finalHighlightInvalid}
                        autoComplete="off"
                        aria-describedby={`${field.descId || `${inputId}-desc`} ${field.errorId || `${inputId}-error`}`.trim()}
                        aria-invalid={finalHighlightInvalid}
                        className="flex-1 border border-border bg-input rounded-l-lg"
                    />

                    <FieldButton
                        onClick={togglePasswordVisibility}
                        disabled={disabled}
                        ariaLabel={showPassword ? 'Hide password' : 'Show password'}
                        variant="right"
                        className="text-brand-primary"
                    >
                        <span className="material-symbols-outlined text-lg" aria-hidden="true">
                            {showPassword ? 'visibility_off' : 'visibility'}
                        </span>
                    </FieldButton>
                </div>
            </FieldRow>
        );
    }
);

PasswordField.displayName = 'PasswordField';

export default PasswordField;
