import React, { useMemo } from 'react';
import { useLogParser } from '../hooks/useLogParser';
import { useLogSearch } from '../hooks/useLogSearch';
import { LogBlock } from './LogBlock';

const HEARTBEAT_PATTERN = /Scheduler is alive\. Uptime:/;

/**
 * LogOutput - Main log display area with parsing and rendering
 * @param {Object} props
 * @param {string} props.logText - Raw log text
 * @param {string} props.searchTerm - Search term for filtering/highlighting
 * @param {Set} [props.activeLevels] - Set of active log levels to show
 * @param {boolean} [props.hideHeartbeat] - Whether to hide scheduler heartbeat messages
 * @returns {JSX.Element}
 */
export const LogOutput = React.memo(
    ({ logText, searchTerm, activeLevels, hideHeartbeat, sortNewestFirst = false }) => {
        // Parse log text into blocks
        const blocks = useLogParser(logText);

        // Filter blocks by search term
        const searchedBlocks = useLogSearch(blocks, searchTerm);

        // Apply level + heartbeat filters, then optionally reverse order
        const filteredBlocks = useMemo(() => {
            const filtered = searchedBlocks.filter(block => {
                // Level filter: blocks with a detected level must match; blocks without a level always show
                if (activeLevels && block.levelClass && !activeLevels.has(block.levelClass)) {
                    return false;
                }
                // Heartbeat filter
                if (hideHeartbeat && block.lines.some(l => HEARTBEAT_PATTERN.test(l))) {
                    return false;
                }
                return true;
            });
            return sortNewestFirst ? [...filtered].reverse() : filtered;
        }, [searchedBlocks, activeLevels, hideHeartbeat, sortNewestFirst]);

        // Empty state
        if (filteredBlocks.length === 0) {
            return (
                <div className="flex-1 overflow-y-auto font-mono text-sm p-3 border border-divider bg-input rounded scrollbar-hidden">
                    <div className="text-secondary">No logs available</div>
                </div>
            );
        }

        return (
            <div className="flex-1 overflow-y-auto font-mono text-sm p-3 border border-divider bg-input rounded scrollbar-hidden">
                {filteredBlocks.map((block, idx) => (
                    <LogBlock
                        key={idx}
                        lines={block.lines}
                        levelClass={block.levelClass}
                        searchTerm={searchTerm}
                    />
                ))}
            </div>
        );
    }
);

LogOutput.displayName = 'LogOutput';
