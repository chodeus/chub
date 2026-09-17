import React from 'react';
import PropTypes from 'prop-types';
import { ButtonBase, ButtonIcon } from './primitives';

/** Icon-only button. A `className` REPLACES the default aspect-square entirely,
 *  and `aria-label` is required because there is no text. */
export const IconButton = React.memo(
    ({
        icon,
        onClick,
        variant = 'ghost',
        size = 'medium',
        disabled = false,
        'aria-label': ariaLabel,
        className = '',
        ...htmlButtonProps
    }) => {
        return (
            <ButtonBase
                onClick={onClick}
                variant={variant}
                size={size}
                disabled={disabled}
                aria-label={ariaLabel}
                className={className || 'aspect-square'}
                {...htmlButtonProps}
            >
                <ButtonIcon icon={icon} size={size} aria-hidden="false" />
            </ButtonBase>
        );
    }
);

IconButton.displayName = 'IconButton';

IconButton.propTypes = {
    icon: PropTypes.string.isRequired,
    onClick: PropTypes.func,
    variant: PropTypes.oneOf(['primary', 'secondary', 'success', 'danger', 'ghost']),
    size: PropTypes.oneOf(['small', 'medium', 'large']),
    disabled: PropTypes.bool,
    'aria-label': PropTypes.string.isRequired,
    className: PropTypes.string,
};
