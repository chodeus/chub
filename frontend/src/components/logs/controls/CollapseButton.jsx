import React from 'react';
import { useLogControls } from '../context/LogControlsContext';

/** Toolbar collapse toggle; the parent decides whether it renders at all, by layout mode. */
export const CollapseButton = () => {
    const { isCollapsed, setIsCollapsed } = useLogControls();

    return (
        <button
            type="button"
            onClick={() => setIsCollapsed(!isCollapsed)}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-primary text-primary-text hover:bg-primary-hover transition-colors min-h-11 font-medium"
            aria-expanded={!isCollapsed}
            aria-controls="log-controls-content"
        >
            <span className="material-symbols-outlined text-xl">
                {isCollapsed ? 'expand_more' : 'expand_less'}
            </span>
            <span className="text-sm">{isCollapsed ? 'Show Controls' : 'Hide Controls'}</span>
        </button>
    );
};
