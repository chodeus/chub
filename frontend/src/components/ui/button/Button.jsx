import React from 'react';
import PropTypes from 'prop-types';
import { ButtonBase, ButtonIcon, ButtonText } from './primitives';

/** Standard button: ButtonBase plus an optional icon; variant and the utility
 *  overrides pass straight through to ButtonBase. */
export const Button = React.memo(
    ({
        children,
        onClick,
        variant = 'primary',
        size = 'medium',
        bgClass = '',
        textClass = '',
        sizeClass = '',
        hoverClass = '',
        disabled = false,
        fullWidth = false,
        icon = null,
        iconPosition = 'left',
        type = 'button',
        className = '',
        ...htmlButtonProps
    }) => {
        return (
            <ButtonBase
                onClick={onClick}
                variant={variant}
                size={size}
                bgClass={bgClass}
                textClass={textClass}
                sizeClass={sizeClass}
                hoverClass={hoverClass}
                disabled={disabled}
                fullWidth={fullWidth}
                type={type}
                className={className}
                {...htmlButtonProps}
            >
                {icon && iconPosition === 'left' && <ButtonIcon icon={icon} size={size} />}
                <ButtonText>{children}</ButtonText>
                {icon && iconPosition === 'right' && <ButtonIcon icon={icon} size={size} />}
            </ButtonBase>
        );
    }
);

Button.displayName = 'Button';

Button.propTypes = {
    children: PropTypes.node.isRequired,
    onClick: PropTypes.func,
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
    disabled: PropTypes.bool,
    fullWidth: PropTypes.bool,
    icon: PropTypes.string,
    iconPosition: PropTypes.oneOf(['left', 'right']),
    type: PropTypes.oneOf(['button', 'submit', 'reset']),
    className: PropTypes.string,
};
