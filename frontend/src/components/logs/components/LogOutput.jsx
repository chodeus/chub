import React, { useMemo, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useLogParser } from '../hooks/useLogParser';
import { useLogSearch } from '../hooks/useLogSearch';
import { LogBlock } from './LogBlock';

const HEARTBEAT_PATTERN = /Scheduler is alive\. Uptime:/;

// Rough initial height per block in px. The virtualizer re-measures after
// render so this only affects the initial scrollbar estimate.
const ESTIMATED_BLOCK_HEIGHT = 22;

/**
 * LogOutput - Main log display area with parsing and rendering
 *
 * Uses @tanstack/react-virtual to render only the blocks currently in view,
 * so multi-megabyte logs don't hang the browser trying to mount tens of
 * thousands of DOM nodes at once.
 *
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

        // Scroll parent for the virtualizer.
        const scrollParentRef = useRef(null);

        const virtualizer = useVirtualizer({
            count: filteredBlocks.length,
            getScrollElement: () => scrollParentRef.current,
            estimateSize: () => ESTIMATED_BLOCK_HEIGHT,
            overscan: 20,
        });

        // Empty state
        if (filteredBlocks.length === 0) {
            return (
                <div
                    className="flex-1 overflow-y-auto font-mono text-sm p-3 border border-divider bg-input rounded scrollbar-hidden"
                >
                    <div className="text-secondary">No logs available</div>
                </div>
            );
        }

        const virtualItems = virtualizer.getVirtualItems();
        const totalSize = virtualizer.getTotalSize();

        return (
            <div
                ref={scrollParentRef}
                className="flex-1 overflow-y-auto font-mono text-sm p-3 border border-divider bg-input rounded scrollbar-hidden"
            >
                <div
                    style={{
                        height: `${totalSize}px`,
                        width: '100%',
                        position: 'relative',
                    }}
                >
                    {virtualItems.map(virtualRow => {
                        const block = filteredBlocks[virtualRow.index];
                        return (
                            <div
                                key={virtualRow.key}
                                data-index={virtualRow.index}
                                ref={virtualizer.measureElement}
                                style={{
                                    position: 'absolute',
                                    top: 0,
                                    left: 0,
                                    width: '100%',
                                    transform: `translateY(${virtualRow.start}px)`,
                                }}
                            >
                                <LogBlock
                                    lines={block.lines}
                                    levelClass={block.levelClass}
                                    searchTerm={searchTerm}
                                />
                            </div>
                        );
                    })}
                </div>
            </div>
        );
    }
);

LogOutput.displayName = 'LogOutput';
