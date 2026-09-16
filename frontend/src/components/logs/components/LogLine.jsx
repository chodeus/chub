import React, { useMemo } from 'react';
import {
    LogLevel,
    LogDateTime,
    LogFilePath,
    LogNumber,
    LogQuoted,
    LogHighlight,
    LogUrl,
    LogFileRef,
} from '../primitives';

// Pre-compiled regex patterns (outside component for performance)
const PATTERNS = {
    combined:
        /(['"]).*?\1|\b\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}:\d{2}\b|\b(CRITICAL|ERROR|WARNING|INFO|DEBUG)\b|https?:\/\/[^\s<>"{}|\\^`\]]+|\[[^\]]+\.(py|js|jsx|ts|tsx|json|yml|yaml|md|txt|log)\]|\b[\w_]+(\.[\w_]+)+\b|\b\d+(\.\d+)?\b/g,
    datetime: /^\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}:\d{2}$/,
    level: /^(CRITICAL|ERROR|WARNING|INFO|DEBUG)$/,
    // Matched first in the combined pattern, so a quote holding a date or URL stays one unit.
    quoted: /^(['"]).*\1$/,
    url: /^https?:\/\//,
    fileref: /^\[[^\]]+\.(py|js|jsx|ts|tsx|json|yml|yaml|md|txt|log)\]$/,
    // Needs a letter in the first segment, or "3.5" and "12.34" classify as paths.
    filepath: /^[\w_]*[A-Za-z_][\w_]*(\.[\w_]+)+$/,
    number: /^\d+(\.\d+)?$/,
};

/** One log line, syntax-highlighted; searchTerm changes highlighting only, never parsing. */
export const LogLine = React.memo(
    ({ line, searchTerm }) => {
        const segments = useMemo(() => {
            // Parse the RAW line: React escapes text children, so pre-escaping double-encodes.
            const result = [];
            let currentIndex = 0;

            let match;
            // Reset regex lastIndex for reuse
            PATTERNS.combined.lastIndex = 0;

            while ((match = PATTERNS.combined.exec(line)) !== null) {
                if (match.index > currentIndex) {
                    const text = line.slice(currentIndex, match.index);
                    if (text) result.push({ type: 'text', content: text });
                }

                const matchedText = match[0];

                // Order matters: the specific patterns must be tried before the general ones.
                if (PATTERNS.quoted.test(matchedText)) {
                    result.push({ type: 'quoted', content: matchedText });
                } else if (PATTERNS.datetime.test(matchedText)) {
                    result.push({ type: 'datetime', content: matchedText });
                } else if (PATTERNS.level.test(matchedText)) {
                    result.push({ type: 'level', content: matchedText });
                } else if (PATTERNS.url.test(matchedText)) {
                    result.push({ type: 'url', content: matchedText });
                } else if (PATTERNS.fileref.test(matchedText)) {
                    result.push({ type: 'fileref', content: matchedText });
                } else if (PATTERNS.filepath.test(matchedText)) {
                    result.push({ type: 'filepath', content: matchedText });
                } else if (PATTERNS.number.test(matchedText)) {
                    result.push({ type: 'number', content: matchedText });
                } else {
                    result.push({ type: 'text', content: matchedText });
                }

                currentIndex = match.index + matchedText.length;
            }

            if (currentIndex < line.length) {
                const text = line.slice(currentIndex);
                if (text) result.push({ type: 'text', content: text });
            }

            return result;
        }, [line]);

        const renderedSegments = useMemo(() => {
            const normalizedSearchTerm = searchTerm?.trim().toLowerCase() || '';
            const hasSearch = normalizedSearchTerm.length > 0;

            // Splits a text segment at the match boundaries so only the matching
            // characters highlight; null when it doesn't match at all.
            const renderTextWithHighlight = (content, key) => {
                if (!hasSearch) return null;
                const lower = content.toLowerCase();
                if (!lower.includes(normalizedSearchTerm)) return null;

                const pieces = [];
                let cursor = 0;
                while (cursor < content.length) {
                    const hit = lower.indexOf(normalizedSearchTerm, cursor);
                    if (hit === -1) {
                        pieces.push(content.slice(cursor));
                        break;
                    }
                    if (hit > cursor) {
                        pieces.push(content.slice(cursor, hit));
                    }
                    const matchText = content.slice(hit, hit + normalizedSearchTerm.length);
                    pieces.push({ match: matchText });
                    cursor = hit + normalizedSearchTerm.length;
                }
                return (
                    <span key={key}>
                        {pieces.map((piece, i) =>
                            typeof piece === 'string' ? (
                                <span key={i}>{piece}</span>
                            ) : (
                                <LogHighlight key={i} searchTerm={normalizedSearchTerm}>
                                    {piece.match}
                                </LogHighlight>
                            )
                        )}
                    </span>
                );
            };

            return segments.map((segment, idx) => {
                const key = `seg-${idx}`;
                const content = segment.content;

                if (segment.type === 'text' || !segment.type) {
                    const highlighted = renderTextWithHighlight(content, key);
                    if (highlighted) return highlighted;
                }

                // Non-text segments highlight whole — splitting them would mangle
                // the segment-specific rendering.
                const shouldHighlight =
                    hasSearch && content.toLowerCase().includes(normalizedSearchTerm);

                let element;
                switch (segment.type) {
                    case 'datetime':
                        element = <LogDateTime key={key}>{content}</LogDateTime>;
                        break;
                    case 'level':
                        element = (
                            <LogLevel key={key} level={content}>
                                {content}
                            </LogLevel>
                        );
                        break;
                    case 'url':
                        element = <LogUrl key={key}>{content}</LogUrl>;
                        break;
                    case 'fileref':
                        element = <LogFileRef key={key}>{content}</LogFileRef>;
                        break;
                    case 'filepath':
                        element = <LogFilePath key={key}>{content}</LogFilePath>;
                        break;
                    case 'number':
                        element = <LogNumber key={key}>{content}</LogNumber>;
                        break;
                    case 'quoted':
                        element = <LogQuoted key={key}>{content}</LogQuoted>;
                        break;
                    case 'text':
                    default:
                        element = <span key={key}>{content}</span>;
                }

                return shouldHighlight ? (
                    <LogHighlight key={key} searchTerm={normalizedSearchTerm}>
                        {element}
                    </LogHighlight>
                ) : (
                    element
                );
            });
        }, [segments, searchTerm]);

        return <div>{renderedSegments}</div>;
    },
    (prevProps, nextProps) => {
        return prevProps.line === nextProps.line && prevProps.searchTerm === nextProps.searchTerm;
    }
);

LogLine.displayName = 'LogLine';
