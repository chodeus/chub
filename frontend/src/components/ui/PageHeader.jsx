import React from 'react';
import PropTypes from 'prop-types';

/**
 * PageHeader - Consistent top-of-page header used across CHUB pages.
 *
 * Supports an optional pastel icon badge (1..5) in the top-left to mirror
 * the Dashboard and Settings splash aesthetic, plus a right-aligned actions
 * slot for CTAs.
 *
 * @param {Object} props
 * @param {string} props.title
 * @param {string} [props.description]
 * @param {number|string} [props.badge] - Pastel badge color 1..5 (requires `icon`).
 * @param {string} [props.icon] - Material symbol name for the badge.
 * @param {React.ReactNode} [props.actions] - Optional right-aligned actions.
 */
export const PageHeader = ({ title, description, badge, icon, actions }) => {
    const hasBadge = badge && icon;

    return (
        <div className="mb-6 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="flex items-start gap-4 min-w-0">
                {hasBadge && (
                    <span
                        className={`badge-bubble badge-bubble--${badge} rounded-full w-12 h-12 shrink-0 flex items-center justify-center`}
                        aria-hidden="true"
                    >
                        <span className="material-symbols-outlined" style={{ fontSize: '24px' }}>
                            {icon}
                        </span>
                    </span>
                )}
                <div className="flex flex-col gap-1 min-w-0">
                    <h1 className="font-display text-3xl font-bold text-primary m-0 leading-tight">
                        {title}
                    </h1>
                    {description && <p className="text-base text-secondary m-0">{description}</p>}
                </div>
            </div>
            {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
        </div>
    );
};

PageHeader.propTypes = {
    title: PropTypes.string.isRequired,
    description: PropTypes.string,
    badge: PropTypes.oneOf([1, 2, 3, 4, 5, '1', '2', '3', '4', '5']),
    icon: PropTypes.string,
    actions: PropTypes.node,
};

export default PageHeader;
