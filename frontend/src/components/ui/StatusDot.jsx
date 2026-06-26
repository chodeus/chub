import React from 'react';
import PropTypes from 'prop-types';

// Status colour + soft ring glow per state. rgba glows aren't expressible as
// theme tokens, so the presentational hexes (mirroring the redesign palette)
// are inlined here.
const DOT = {
    success: ['#6cbc66', 'rgba(108,188,102,.16)'],
    running: ['#53e8f0', 'rgba(83,232,240,.18)'],
    error: ['#fd355c', 'rgba(253,53,92,.18)'],
    warning: ['#ffc944', 'rgba(255,201,68,.16)'],
    pending: ['#ffc944', 'rgba(255,201,68,.16)'],
    info: ['#53e8f0', 'rgba(83,232,240,.18)'],
    idle: ['#564f8a', 'rgba(86,79,138,0)'],
};

/**
 * Small status dot with an optional soft ring. `status` keys map to the
 * redesign palette; pass a raw `color` to override.
 */
const StatusDot = ({ status = 'idle', size = 7, ring = true, color, className = '' }) => {
    const [c, glow] = DOT[status] || DOT.idle;
    return (
        <span
            className={`shrink-0 rounded-full ${className}`}
            style={{
                width: size,
                height: size,
                background: color || c,
                boxShadow: ring ? `0 0 0 3px ${glow}` : undefined,
            }}
            aria-hidden="true"
        />
    );
};

StatusDot.propTypes = {
    status: PropTypes.oneOf(['success', 'running', 'error', 'warning', 'pending', 'info', 'idle']),
    size: PropTypes.number,
    ring: PropTypes.bool,
    color: PropTypes.string,
    className: PropTypes.string,
};

export default StatusDot;
