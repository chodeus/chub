import React from 'react';

// Build-style stamp for a poster corner, shared by the Unmatched, Asset Search and
// CL2K Maker grids. The caller supplies position and text size via `className`.
const STYLE_COLOR = {
    CL2K: { text: '#c9bcff', border: 'rgba(135,103,247,0.55)' },
    MM2K: { text: '#ffd257', border: 'rgba(255,201,68,0.5)' },
    // Artwork drives carry logos/backgrounds/squareart, not posters.
    ARTWORK: { text: '#7fe3c4', border: 'rgba(64,208,168,0.5)' },
};
const DEFAULT_COLOR = { text: '#ffffff', border: 'rgba(255,255,255,0.25)' };

export const StyleStamp = ({ style, className = '' }) => {
    if (!style) return null;
    const color = STYLE_COLOR[String(style).toUpperCase()] || DEFAULT_COLOR;
    return (
        <span
            className={`font-mono font-bold tracking-[0.4px] px-1.5 py-0.5 rounded-[4px] border backdrop-blur-sm ${className}`}
            style={{
                color: color.text,
                borderColor: color.border,
                background: 'rgba(13,10,26,0.8)',
            }}
            title={`Style: ${style}`}
        >
            {style}
        </span>
    );
};

export default StyleStamp;
