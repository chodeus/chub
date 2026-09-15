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
// Dense control-panel header (redesign). The legacy pastel `badge`/`icon`
// bubble is intentionally ignored now that pages lead with a flush title row.
export const PageHeader = ({ title, description, actions }) => {
    return (
        <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
                <h1 className="font-display text-[26px] font-bold tracking-[-0.3px] text-fg m-0">
                    {title}
                </h1>
                {description && (
                    <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">{description}</p>
                )}
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
