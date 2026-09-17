import React from 'react';
import PropTypes from 'prop-types';
import { ButtonBase, ButtonIcon, ButtonText, ButtonSpinner } from './primitives';

/** Button that swaps its icon for a spinner while `loading`. */
export const LoadingButton = React.memo(
    ({
        children,
        onClick,
        loading = false,
        loadingText = 'Loading...',
        variant = 'primary',
        size = 'medium',
        disabled = false,
        fullWidth = false,
        icon = null,
        className = '',
        ...htmlButtonProps
    }) => {
        return (
            <ButtonBase
                onClick={onClick}
                variant={variant}
                size={size}
                disabled={disabled || loading}
                fullWidth={fullWidth}
                className={className}
                {...htmlButtonProps}
            >
                {loading ? (
                    <>
                        <ButtonSpinner size={size} />
                        <ButtonText>{loadingText}</ButtonText>
                    </>
                ) : (
                    <>
                        {icon && <ButtonIcon icon={icon} size={size} />}
                        <ButtonText>{children}</ButtonText>
                    </>
                )}
            </ButtonBase>
        );
    }
);

LoadingButton.displayName = 'LoadingButton';

LoadingButton.propTypes = {
    children: PropTypes.node.isRequired,
    onClick: PropTypes.func,
    loading: PropTypes.bool,
    loadingText: PropTypes.string,
    variant: PropTypes.oneOf(['primary', 'secondary', 'success', 'danger', 'ghost']),
    size: PropTypes.oneOf(['small', 'medium', 'large']),
    disabled: PropTypes.bool,
    fullWidth: PropTypes.bool,
    icon: PropTypes.string,
    className: PropTypes.string,
};
