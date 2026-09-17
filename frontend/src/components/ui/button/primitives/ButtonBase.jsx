import React, { useCallback } from 'react';
import PropTypes from 'prop-types';

/** Core button primitive; `variant` supplies the styling.
 *  The bgClass/textClass/sizeClass/hoverClass overrides WIN over the variant. */
export const ButtonBase = React.memo(
    ({
        children,
        onClick,
        disabled = false,
        variant = 'primary',
        size = 'medium',
        bgClass = '',
        textClass = '',
        sizeClass = '',
        hoverClass = '',
        fullWidth = false,
        type = 'button',
        className = '',
        'aria-label': ariaLabel,
        ...htmlButtonProps
    }) => {
        // Handle click with disabled check
        const handleClick = useCallback(
            event => {
                if (!disabled && onClick) {
                    onClick(event);
                }
            },
            [disabled, onClick]
        );

        // Build class names from utility classes
        // Base styles: layout, spacing, typography, cursor, transitions
        const baseClasses = [
            'inline-flex',
            'items-center',
            'justify-center',
            'border-0',
            'font-medium',
            'cursor-pointer',
            'transition-all',
            'duration-150',
        ];

        // Variant background colors (overridden by bgClass)
        const variantBgClasses = {
            primary: 'bg-primary',
            secondary: 'bg-surface-alt',
            success: 'bg-success',
            danger: 'bg-danger',
            ghost: 'bg-transparent',
            warning: 'bg-warning',
            info: 'bg-info',
            muted: 'bg-surface-inset',
            surface: 'bg-surface',
        };

        // Variant text colors (overridden by textClass)
        const variantTextClasses = {
            primary: 'text-on-color',
            secondary: 'text-fg',
            success: 'text-on-color',
            danger: 'text-on-color',
            ghost: 'text-fg',
            warning: 'text-on-color', // White text on warning bg
            info: 'text-on-color', // White text on info bg
            muted: 'text-fg', // Primary text on muted bg
            surface: 'text-fg', // Primary text on surface bg
        };

        // Ghost variant needs border (not overridden by bgClass/textClass)
        const variantBorderClasses = variant === 'ghost' ? ['border', 'border-border'] : [];

        // Size styles: dimensions and spacing (overridden by sizeClass)
        const variantSizeClasses = {
            // 36px is a design spec, so touch-expand grows only the coarse-pointer hit area.
            small: ['min-h-9', 'touch-expand', 'px-3', 'py-1.5', 'text-sm'],
            medium: ['min-h-11', 'px-4', 'py-2', 'text-base'],
            large: ['min-h-12', 'px-5', 'py-3', 'text-lg'],
        };

        // Variant hover states (overridden by hoverClass)
        // Note: Using opacity for subtle hover effects - works with all colors
        const variantHoverClasses = {
            primary: 'hover:opacity-90',
            secondary: 'hover:opacity-90',
            success: 'hover:opacity-90',
            danger: 'hover:opacity-90',
            ghost: 'hover:bg-surface-elevated',
            warning: 'hover:opacity-90',
            info: 'hover:opacity-90',
            muted: 'hover:opacity-90',
            surface: 'hover:bg-surface-elevated',
        };

        // State styles: active, disabled, focus
        const stateClasses = [
            'active:translate-y-0',
            'disabled:opacity-50',
            'disabled:cursor-not-allowed',
            'focus-visible:outline',
            'focus-visible:outline-2',
            'focus-visible:outline-offset-2',
            'focus-visible:outline-focus',
        ];

        // Border radius
        const roundedClasses = ['rounded-lg'];

        // Full width
        const widthClasses = fullWidth ? ['w-full'] : [];

        // Compose all utility classes with override precedence
        // Precedence: Base → Variant (unless overridden) → Overrides → className
        const buttonClasses = [
            ...baseClasses,
            ...variantBorderClasses, // Ghost border (always applied)
            !bgClass && (variantBgClasses[variant] || variantBgClasses.primary), // Variant bg (unless overridden)
            !textClass && (variantTextClasses[variant] || variantTextClasses.primary), // Variant text (unless overridden)
            !sizeClass && (variantSizeClasses[size] || variantSizeClasses.medium).join(' '), // Variant size (unless overridden)
            bgClass, // Utility bg override
            textClass, // Utility text override
            sizeClass, // Utility size override
            ...roundedClasses,
            ...stateClasses,
            !hoverClass && (variantHoverClasses[variant] || variantHoverClasses.primary), // Variant hover (unless overridden)
            hoverClass, // Utility hover override
            ...widthClasses,
            className, // Final catch-all
        ]
            .filter(Boolean)
            .join(' ');

        return (
            <button
                className={buttonClasses}
                onClick={handleClick}
                disabled={disabled}
                type={type}
                aria-label={ariaLabel}
                {...htmlButtonProps}
            >
                {children}
            </button>
        );
    }
);

ButtonBase.displayName = 'ButtonBase';

ButtonBase.propTypes = {
    children: PropTypes.node,
    onClick: PropTypes.func,
    disabled: PropTypes.bool,
    variant: PropTypes.oneOf([
        'primary',
        'secondary',
        'success',
        'danger',
        'ghost',
        'warning',
        'info',
        'muted',
        'surface',
    ]),
    size: PropTypes.oneOf(['small', 'medium', 'large']),
    bgClass: PropTypes.string,
    textClass: PropTypes.string,
    sizeClass: PropTypes.string,
    hoverClass: PropTypes.string,
    fullWidth: PropTypes.bool,
    type: PropTypes.oneOf(['button', 'submit', 'reset']),
    className: PropTypes.string,
    'aria-label': PropTypes.string,
};
