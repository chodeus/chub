import React from 'react';
import { LogLine } from './LogLine';

/** One block of log lines — a multi-line entry such as a stack trace. */
export const LogBlock = React.memo(
    ({ lines, levelClass, searchTerm }) => {
        return (
            <div className={`log-block ${levelClass ? `log-block--${levelClass}` : ''}`}>
                {lines.map((line, idx) => (
                    <LogLine key={idx} line={line} searchTerm={searchTerm} />
                ))}
            </div>
        );
    },
    // Custom comparison: only re-render if lines, levelClass, or searchTerm changed
    (prevProps, nextProps) => {
        // Shallow array comparison - lines array itself should be stable
        return (
            prevProps.lines === nextProps.lines &&
            prevProps.levelClass === nextProps.levelClass &&
            prevProps.searchTerm === nextProps.searchTerm
        );
    }
);

LogBlock.displayName = 'LogBlock';
