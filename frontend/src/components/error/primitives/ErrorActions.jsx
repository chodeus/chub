import React from 'react';
import PropTypes from 'prop-types';
import { Button } from '../../ui/button/Button';

/** Row of recovery buttons; `onAction` receives the clicked action's id. */
export const ErrorActions = ({ actions = [], onAction, mode = 'page' }) => {
    if (actions.length === 0) return null;

    const containerClass =
        mode === 'page' ? 'mb-6 flex flex-wrap gap-2' : 'flex flex-wrap gap-2 mb-0';

    return (
        <div className={containerClass}>
            {actions.map(action => (
                <Button
                    key={action.id}
                    variant={action.variant || 'secondary'}
                    onClick={() => onAction(action.id)}
                    disabled={action.disabled}
                    icon={action.icon}
                    className="gap-1"
                >
                    {action.label}
                </Button>
            ))}
        </div>
    );
};

ErrorActions.propTypes = {
    actions: PropTypes.arrayOf(
        PropTypes.shape({
            id: PropTypes.string.isRequired,
            label: PropTypes.string.isRequired,
            variant: PropTypes.oneOf(['primary', 'secondary', 'success', 'danger']),
            icon: PropTypes.string,
            disabled: PropTypes.bool,
        })
    ),
    onAction: PropTypes.func.isRequired,
    mode: PropTypes.oneOf(['page', 'modal', 'inline']),
};
