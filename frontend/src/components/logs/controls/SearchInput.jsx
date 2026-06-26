import { useState } from 'react';
import { useLogControls } from '../context/LogControlsContext';

/**
 * SearchInput — compact dark-inset filter field with a leading search icon, a
 * ⌘F hint when empty, and a clear button when filled. Matches the redesign mock.
 */
export const SearchInput = () => {
    const { onSearchChange } = useLogControls();
    const [searchValue, setSearchValue] = useState('');

    const handleChange = e => {
        const value = e.target.value;
        setSearchValue(value);
        onSearchChange(value);
    };

    const handleClear = () => {
        setSearchValue('');
        onSearchChange('');
    };

    return (
        <div className="flex items-center gap-2 w-full h-9 px-3 rounded-lg bg-surface-inset border border-border focus-within:border-primary transition-colors">
            <span
                className="material-symbols-outlined text-[16px] text-fg-subtle shrink-0"
                aria-hidden="true"
            >
                search
            </span>
            <input
                type="text"
                value={searchValue}
                onChange={handleChange}
                placeholder="Filter lines…"
                aria-label="Search logs"
                className="flex-1 min-w-0 bg-transparent border-0 outline-none text-[13px] text-fg placeholder:text-fg-dim"
            />
            {searchValue ? (
                <button
                    type="button"
                    onClick={handleClear}
                    className="shrink-0 text-fg-muted hover:text-fg transition-colors flex items-center"
                    aria-label="Clear search"
                >
                    <span className="material-symbols-outlined text-[18px]">cancel</span>
                </button>
            ) : (
                <span className="shrink-0 font-mono text-[11px] text-fg-faint pointer-events-none">
                    ⌘F
                </span>
            )}
        </div>
    );
};
