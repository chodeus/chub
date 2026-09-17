import React from 'react';
import PropTypes from 'prop-types';

/** Dense control-panel header: flush title row, optional description, right-aligned actions. */
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
    actions: PropTypes.node,
};

export default PageHeader;
