import React from 'react';
import PropTypes from 'prop-types';
import { ButtonBase, ButtonIcon, ButtonText, ButtonSpinner } from '../ui/button/primitives';

/**
 * ToolBarButton - horizontal icon+label button.
 *
 * Variants:
 * - "ghost" (default): subtle, background on hover. Good for secondary actions (Reset, Cancel).
 * - "primary": indigo fill. Good for save / commit actions.
 *
 * @param {Object} props
 * @param {string} props.label
 * @param {string} props.iconName - Material symbol name.
 * @param {"ghost"|"primary"} [props.variant="ghost"]
 * @param {boolean} [props.isSpinning=false]
 * @param {boolean} [props.isDisabled=false]
 * @param {Function} [props.onPress]
 */
const Button = React.forwardRef(
    (
        {
            label,
            iconName,
            variant = 'ghost',
            isSpinning = false,
            isDisabled = false,
            onPress,
            ...otherProps
        },
        ref
    ) => {
        const layout = 'flex-row items-center gap-2 px-3 py-2 rounded-lg min-h-10';
        return (
            <ButtonBase
                ref={ref}
                onClick={onPress}
                disabled={isDisabled || isSpinning}
                variant={variant}
                className={layout}
                aria-label={label}
                {...otherProps}
            >
                {isSpinning ? (
                    <ButtonSpinner size="small" />
                ) : (
                    <ButtonIcon icon={iconName} size="small" />
                )}
                <ButtonText className="text-sm font-medium">{label}</ButtonText>
            </ButtonBase>
        );
    }
);

Button.displayName = 'ToolBarButton';

Button.propTypes = {
    label: PropTypes.string.isRequired,
    iconName: PropTypes.string.isRequired,
    variant: PropTypes.oneOf(['ghost', 'primary']),
    isSpinning: PropTypes.bool,
    isDisabled: PropTypes.bool,
    onPress: PropTypes.func,
};

export default Button;
