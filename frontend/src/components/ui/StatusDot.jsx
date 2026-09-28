import React from 'react';
import PropTypes from 'prop-types';

// Theme token and ring opacity per state; the ring is the dot's own colour.
const DOT = {
    success: ['var(--success)', 16],
    running: ['var(--accent)', 18],
    error: ['var(--error)', 18],
    warning: ['var(--warning)', 16],
    pending: ['var(--warning)', 16],
    info: ['var(--info)', 18],
    idle: ['var(--text-faint)', 0],
};

/** Status dot with an optional soft ring, coloured by its theme token. */
const StatusDot = ({ status = 'idle', size = 7, ring = true, color, className = '' }) => {
    const [token, ringPct] = DOT[status] || DOT.idle;
    const fill = color || token;
    return (
        <span
            className={`shrink-0 rounded-full ${className}`}
            style={{
                width: size,
                height: size,
                background: fill,
                boxShadow:
                    ring && ringPct
                        ? `0 0 0 3px color-mix(in srgb, ${fill} ${ringPct}%, transparent)`
                        : undefined,
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
