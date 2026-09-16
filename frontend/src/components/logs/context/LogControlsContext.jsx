import { createContext, useContext, useState } from 'react';

// Match UIStateContext's mobile breakpoint so the panel starts collapsed on phones.
const MOBILE_BREAKPOINT = 768;

const getInitialCollapsed = () => {
    if (typeof window === 'undefined') return false;
    return window.innerWidth < MOBILE_BREAKPOINT;
};

/** Shared state for the log control bar: selections, search, collapse. */
const LogControlsContext = createContext(null);

/** Provides control state to the log control subcomponents. */
export function LogControlsProvider({
    children,
    modules,
    logFiles,
    selectedModule,
    selectedLogFile,
    searchInputRef,
    onModuleChange,
    onLogFileChange,
    onSearchChange,
    onDownload,
}) {
    const [isCollapsed, setIsCollapsed] = useState(getInitialCollapsed);

    const value = {
        // State
        modules,
        logFiles,
        selectedModule,
        selectedLogFile,
        isCollapsed,
        searchInputRef,
        // Actions
        onModuleChange,
        onLogFileChange,
        onSearchChange,
        onDownload,
        setIsCollapsed,
    };

    return <LogControlsContext.Provider value={value}>{children}</LogControlsContext.Provider>;
}

/** Access control state; throws outside LogControlsProvider. */
export function useLogControls() {
    const context = useContext(LogControlsContext);

    if (!context) {
        throw new Error('useLogControls must be used within LogControlsProvider');
    }

    return context;
}
