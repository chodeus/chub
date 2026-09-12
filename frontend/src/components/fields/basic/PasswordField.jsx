import React, { useState, useCallback } from 'react';
import { FieldRow, InputBase } from '../primitives';
import { FieldButton } from '../features/shared';
import { configAPI } from '../../../utils/api';
import { SECRET_INPUT_PROPS } from '../../../utils/forms/secretInput.js';

// Saved secrets arrive from the backend redacted to this placeholder; the real
// value is only ever fetched on demand via configAPI.revealSecret.
const REDACTED = '********';

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
        // When present, the eye toggle can fetch and show the real saved secret.
        const secretPath = field.secretPath ?? null;

        const [showPassword, setShowPassword] = useState(false);
        // Real secret fetched for display only — never pushed into form state,
        // so revealing never dirties the form or re-saves the value.
        const [revealedValue, setRevealedValue] = useState(null);
        const [revealError, setRevealError] = useState(false);
        const [revealing, setRevealing] = useState(false);

        const handleChange = useCallback(
            e => {
                // User is typing a new secret — drop the revealed value so the
                // field behaves like a normal editable input from here on.
                setRevealedValue(null);
                setRevealError(false);
                onChange(e.target.value);
            },
            [onChange]
        );

        const togglePasswordVisibility = useCallback(async () => {
            const next = !showPassword;
            // Revealing a saved-but-redacted secret we don't hold yet: fetch the
            // real value before switching the input to plain text.
            if (next && secretPath && revealedValue === null && value === REDACTED) {
                setRevealing(true);
                setRevealError(false);
                try {
                    const res = await configAPI.revealSecret(secretPath);
                    setRevealedValue(res?.data?.value ?? '');
                } catch {
                    setRevealError(true);
                    setRevealing(false);
                    return; // stay masked and surface the error
                }
                setRevealing(false);
            }
            setShowPassword(next);
        }, [showPassword, secretPath, revealedValue, value]);

        const inputId = field.id || `field-${field.key}`;
        // Show the fetched real secret once we have it; otherwise the prop value
        // (which for a saved secret is the "********" placeholder).
        const displayValue = revealedValue ?? value ?? '';

        return (
            <FieldRow
                htmlFor={inputId}
                label={field.label}
                required={field.required}
                description={field.description}
                error={errorMessage || (revealError ? 'Could not reveal secret' : null)}
                invalid={highlightInvalid}
            >
                <div className="flex">
                    <InputBase
                        id={inputId}
                        type={showPassword ? 'text' : 'password'}
                        name={field.key}
                        value={displayValue}
                        placeholder={field.placeholder}
                        disabled={disabled}
                        required={field.required}
                        maxLength={field.maxLength}
                        minLength={field.minLength}
                        onChange={handleChange}
                        onBlur={onBlur}
                        invalid={highlightInvalid}
                        {...SECRET_INPUT_PROPS}
                        aria-describedby={`${field.descId || `${inputId}-desc`} ${field.errorId || `${inputId}-error`}`.trim()}
                        aria-invalid={highlightInvalid}
                        className="flex-1 border border-border bg-input rounded-l-lg"
                    />

                    <FieldButton
                        onClick={togglePasswordVisibility}
                        disabled={disabled || revealing}
                        ariaLabel={showPassword ? 'Hide password' : 'Show password'}
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
