import React, { useCallback } from 'react';

/**
 * Enhanced time input component with 24-hour validation
 * @param {string} id - Input id, for label binding
 * @param {string} ariaLabel - Accessible name when no <label> is bound to the input
 * @param {string} value - Time value in HH:mm format (24-hour)
 * @param {Function} onChange - Value change callback
 * @param {boolean} disabled - Whether the input is disabled
 * @param {boolean} required - Whether the input is required
 * @param {string} placeholder - Placeholder text
 * @param {string} className - Additional CSS classes
 */
export const TimeInput = React.memo(
    ({
        id,
        ariaLabel,
        value = '12:00',
        onChange,
        disabled = false,
        required = false,
        placeholder = '12:00',
        className = '',
    }) => {
        const handleChange = useCallback(
            e => {
                const newValue = e.target.value;
                // Basic validation for 24-hour format (HH:mm)
                if (newValue === '' || /^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$/.test(newValue)) {
                    onChange(newValue);
                }
            },
            [onChange]
        );

        return (
            <input
                id={id}
                aria-label={ariaLabel}
                type="time"
                value={value || ''}
                onChange={handleChange}
                disabled={disabled}
                required={required}
                placeholder={placeholder}
                className={`
                px-3 py-2 border border-border rounded-lg
                min-h-11 bg-input text-fg
                transition-colors duration-200
                ${
                    disabled
                        ? 'opacity-50 cursor-not-allowed bg-surface-disabled'
                        : 'hover:border-border-hover focus:outline-none focus:ring-2 focus:ring-primary focus:border-primary'
                }
                ${className}
            `}
            />
        );
    }
);

TimeInput.displayName = 'TimeInput';

export default TimeInput;
