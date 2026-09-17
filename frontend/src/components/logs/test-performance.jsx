import React, { useEffect, useRef, useState } from 'react';
import { LogOutput } from './components';

/** Generates `lineCount` fake log lines, roughly one in ten followed by a stack trace. */
function generateTestLog(lineCount) {
    const levels = ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'];
    const modules = ['sync_gdrive', 'border_replacerr', 'poster_renamerr', 'health_checkarr'];
    const messages = [
        'Operation completed successfully',
        'Processing file: poster_image_123.jpg',
        'Connection timeout after 30s',
        'Invalid API key provided',
        'Cache updated with 42 entries',
    ];

    const lines = [];
    for (let i = 0; i < lineCount; i++) {
        const level = levels[Math.floor(Math.random() * levels.length)];
        const module = modules[Math.floor(Math.random() * modules.length)];
        const message = messages[Math.floor(Math.random() * messages.length)];
        const timestamp = `01/01/24 ${String(Math.floor(Math.random() * 24)).padStart(2, '0')}:${String(Math.floor(Math.random() * 60)).padStart(2, '0')}:${String(Math.floor(Math.random() * 60)).padStart(2, '0')} ${Math.random() > 0.5 ? 'AM' : 'PM'}`;

        lines.push(`${timestamp} - ${level} - ${module}: ${message}`);

        // Add occasional stack trace (multi-line)
        if (Math.random() > 0.9) {
            lines.push('  File "util/base_module.py", line 123, in run');
            lines.push('    raise ValueError("Invalid configuration")');
            lines.push('ValueError: Invalid configuration');
        }
    }

    return lines.join('\n');
}

/** Dev harness: renders `lineCount` generated entries plus occasional stack traces, and times the render. */
export function LogPerformanceTest() {
    const [logText, setLogText] = useState('');
    const [renderTime, setRenderTime] = useState(null);
    const [lineCount, setLineCount] = useState(1000);

    const frameRef = useRef(0);
    useEffect(() => () => cancelAnimationFrame(frameRef.current), []);

    const handleGenerate = () => {
        // Clock starts AFTER generation — including it measured the generator, not the
        // render. Two frames: the first runs after commit, the second after paint.
        const generated = generateTestLog(lineCount);
        const startTime = performance.now();
        setLogText(generated);
        // A second click must not strand the first measurement's callbacks: the ref
        // holds whichever frame is still outstanding, so cancelling it is enough.
        cancelAnimationFrame(frameRef.current);
        frameRef.current = requestAnimationFrame(() => {
            frameRef.current = requestAnimationFrame(() => {
                setRenderTime(performance.now() - startTime);
            });
        });
    };

    return (
        <div className="flex flex-col gap-4 p-4" style={{ height: '100vh' }}>
            <div className="flex gap-4 items-center">
                <input
                    type="number"
                    value={lineCount}
                    onChange={e => setLineCount(parseInt(e.target.value) || 1000)}
                    className="border border-default rounded-md p-2"
                    min="100"
                    max="10000"
                    step="100"
                />
                <button
                    onClick={handleGenerate}
                    className="bg-primary text-white px-4 py-2 rounded-md"
                >
                    Generate {lineCount} Lines
                </button>
                {renderTime !== null && (
                    <span className={renderTime <= 100 ? 'text-success' : 'text-warning'}>
                        Render time: {renderTime.toFixed(2)}ms
                        {renderTime <= 100 ? ' ✓ PASS' : ' ⚠ SLOW'}
                    </span>
                )}
            </div>
            <LogOutput logText={logText} searchTerm="" />
        </div>
    );
}
