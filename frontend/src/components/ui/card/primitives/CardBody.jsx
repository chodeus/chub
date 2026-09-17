import React from 'react';
import PropTypes from 'prop-types';

/** Card body container. */
export const CardBody = React.memo(({ children, className = '' }) => {
    return (
        <div className={`flex-1 p-3 sm:p-5 text-fg leading-relaxed ${className}`}>{children}</div>
    );
});

CardBody.displayName = 'CardBody';

CardBody.propTypes = {
    children: PropTypes.node.isRequired,
    className: PropTypes.string,
};
