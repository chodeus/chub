import React from 'react';
import { LogControlsProvider } from '../context/LogControlsContext';
import { CollapseButton } from './CollapseButton';
import { ModuleSelect } from './ModuleSelect';
import { LogFileSelect } from './LogFileSelect';
import { SearchInput } from './SearchInput';
import { ActionButtons } from './ActionButtons';
import { useLogControls } from '../context/LogControlsContext';
import { useUIState } from '../../../contexts/UIStateContext';

/** Control bar UI: stacked with a collapse toggle under 1200px, a wrapping row above it. */
const LogControlsContent = ({ logText }) => {
    const { isCollapsed } = useLogControls();
    const { viewport } = useUIState();

    // Use stacked layout for narrower viewports (< 1200px)
    // This gives more vertical space when horizontal space is limited
    const useStackedLayout = viewport.width < 1200;

    return (
        <div className="flex flex-col gap-3 px-4 py-3.5">
            {/* Show/Hide toggle - always visible in stacked layout */}
            {useStackedLayout && <CollapseButton />}

            {/* Collapse only exists in stacked layout — never hide controls without its toggle. */}
            {(!useStackedLayout || !isCollapsed) && (
                <div
                    id="log-controls-content"
                    className={
                        useStackedLayout
                            ? 'flex flex-col gap-2'
                            : 'flex flex-wrap items-center gap-2'
                    }
                >
                    {useStackedLayout ? (
                        <>
                            {/* Stacked layout: Full-width rows */}
                            <ModuleSelect />
                            <LogFileSelect />
                            <SearchInput />
                            <div className="flex justify-center">
                                <ActionButtons logText={logText} />
                            </div>
                        </>
                    ) : (
                        <>
                            {/* Horizontal layout: a row that wraps when it runs out of width */}
                            <div className="flex-shrink-0 min-w-48">
                                <ModuleSelect />
                            </div>
                            <div className="flex-shrink-0 min-w-48">
                                <LogFileSelect />
                            </div>
                            <div className="flex-1 min-w-64">
                                <SearchInput />
                            </div>
                            <div className="flex-shrink-0">
                                <ActionButtons logText={logText} />
                            </div>
                        </>
                    )}
                </div>
            )}
        </div>
    );
};

/** Root control toolbar: owns LogControlsProvider and composes the subcomponents. */
export const LogControls = ({
    modules,
    logFiles,
    selectedModule,
    selectedLogFile,
    logText,
    searchInputRef,
    onModuleChange,
    onLogFileChange,
    onSearchChange,
    onDownload,
}) => {
    return (
        <LogControlsProvider
            modules={modules}
            logFiles={logFiles}
            selectedModule={selectedModule}
            selectedLogFile={selectedLogFile}
            searchInputRef={searchInputRef}
            onModuleChange={onModuleChange}
            onLogFileChange={onLogFileChange}
            onSearchChange={onSearchChange}
            onDownload={onDownload}
        >
            <LogControlsContent logText={logText} />
        </LogControlsProvider>
    );
};
