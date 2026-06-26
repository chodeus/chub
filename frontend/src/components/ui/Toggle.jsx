import React from 'react';
import PropTypes from 'prop-types';

/**
 * Toggle switch — 38×22 pill with a 16px white knob. On = brand fill (knob
 * left 19px), off = border-grey (knob left 3px). Per the redesign spec.
 */
const Toggle = ({ checked = false, onChange, disabled = false, label, className = '' }) => (
    <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => !disabled && onChange?.(!checked)}
        className={`relative shrink-0 rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${className}`}
        style={{ width: 38, height: 22, background: checked ? 'var(--primary)' : '#2a3052' }}
    >
        <span
            className="absolute rounded-full bg-white transition-all"
            style={{ width: 16, height: 16, top: 3, left: checked ? 19 : 3 }}
            aria-hidden="true"
        />
    </button>
);

Toggle.propTypes = {
    checked: PropTypes.bool,
    onChange: PropTypes.func,
    disabled: PropTypes.bool,
    label: PropTypes.string,
    className: PropTypes.string,
};

export default Toggle;
