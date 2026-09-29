import React from 'react';
import PropTypes from 'prop-types';

/** Dense control-panel header: flush title row, optional description, right-aligned actions. */
export const PageHeader = ({ title, description, actions }) => {
    return (
        <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
                <h1 className="font-display text-title font-bold tracking-[-0.3px] text-fg m-0">
                    {title}
                </h1>
                {description && (
                    <p className="text-fg-subtle text-dense mt-1 mb-0">{description}</p>
                )}
            </div>
            {/* gap-y-3 clears a Toggle's 44px coarse hit box once the actions wrap. */}
            {actions && (
                <div className="flex flex-wrap items-center gap-x-2.5 gap-y-3 shrink-0 max-w-full">
                    {actions}
                </div>
            )}
        </div>
    );
};

PageHeader.propTypes = {
    title: PropTypes.string.isRequired,
    description: PropTypes.node,
    actions: PropTypes.node,
};

export default PageHeader;
