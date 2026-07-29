import React, { useId, useState } from 'react';
import PropTypes from 'prop-types';

/**
 * Inline info affordance: a small ⓘ that reveals longer help text on hover or
 * keyboard focus. Sits next to a field label so the inline description can stay
 * short while the full guidance (the field's `helpText`) stays one reveal away.
 * Renders nothing when there is no text to show.
 *
 * Hover and focus-within alone left every field's helpText unreachable on a
 * touch screen, so the button also toggles it outright.
 */
const InfoTooltip = ({ text, label = 'More info' }) => {
    const [open, setOpen] = useState(false);
    const tooltipId = useId();
    if (!text) return null;
    return (
        <span className="group/tip relative inline-flex align-middle">
            <button
                type="button"
                aria-label={label}
                aria-expanded={open}
                aria-describedby={open ? tooltipId : undefined}
                onClick={() => setOpen(o => !o)}
                onBlur={() => setOpen(false)}
                className="inline-flex items-center justify-center text-fg-faint hover:text-fg-muted focus-visible:text-fg-muted outline-none cursor-help touch-expand"
            >
                <span className="material-symbols-outlined text-[15px] leading-none">info</span>
            </button>
            <span
                id={tooltipId}
                role="tooltip"
                className={`pointer-events-none absolute left-0 top-[calc(100%+6px)] w-[240px] max-w-[70vw] rounded-lg border border-border bg-surface-elevated p-2.5 text-[12px] font-normal leading-relaxed text-fg-muted group-hover/tip:block group-focus-within/tip:block ${
                    open ? 'block' : 'hidden'
                }`}
                style={{ zIndex: 60, boxShadow: '0 8px 24px -8px rgba(0,0,0,.7)' }}
            >
                {text}
            </span>
        </span>
    );
};

InfoTooltip.propTypes = {
    text: PropTypes.string,
    label: PropTypes.string,
};

export default InfoTooltip;
