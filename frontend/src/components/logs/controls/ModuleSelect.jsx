import React from 'react';
import { useLogControls } from '../context/LogControlsContext';
import { humanize } from '../../../utils/tools';

/**
 * ModuleSelect — compact dark-inset module picker with a leading status dot,
 * matching the redesign mock.
 */
export const ModuleSelect = () => {
    const { modules, selectedModule, onModuleChange } = useLogControls();

    return (
        <div className="flex items-center gap-2 w-full h-11 px-3 rounded-lg bg-surface-inset border border-border focus-within:border-primary transition-colors">
            <span
                className={`w-[7px] h-[7px] rounded-full shrink-0 ${
                    selectedModule ? 'bg-accent' : 'bg-fg-faint'
                }`}
                aria-hidden="true"
            />
            <select
                value={selectedModule || ''}
                onChange={e => onModuleChange(e.target.value)}
                aria-label="Select module"
                className="flex-1 min-w-0 h-full bg-transparent border-0 outline-none text-[13px] text-fg cursor-pointer"
            >
                <option value="">Select module</option>
                {modules.map(module => (
                    <option key={module} value={module}>
                        {humanize(module)}
                    </option>
                ))}
            </select>
        </div>
    );
};
