import { render, screen } from '@testing-library/react';
import { LogLine } from './LogLine.jsx';

describe('LogLine', () => {
    it('picks out the timestamp, the level and a quoted title', () => {
        render(
            <LogLine
                line={'09/16/2026 08:15:04 INFO Imported "Blade Runner" from the queue'}
                searchTerm=""
            />
        );

        expect(screen.getByText('09/16/2026 08:15:04')).toBeInTheDocument();
        expect(screen.getByText('INFO')).toBeInTheDocument();
        expect(screen.getByText('"Blade Runner"')).toHaveClass('text-warning');
    });

    it('treats a dotted name as a path but a measurement as plain text', () => {
        render(<LogLine line="INFO util/tools.py finished in 12.34ms" searchTerm="" />);

        expect(screen.getByText('tools.py')).toHaveClass('text-info');
        // Regression: the first segment needs a letter, or every decimal reads as a path.
        expect(screen.getByText('12.34ms')).not.toHaveClass('text-info');
    });

    it('keeps a placeholder token that came from the log itself, not from a quote', () => {
        render(<LogLine line="skipped __QUOTED_PLACEHOLDER_0__ (no match)" searchTerm="" />);

        expect(screen.getByText('__QUOTED_PLACEHOLDER_0__')).toBeInTheDocument();
    });

    it('highlights only the matching characters of a search term', () => {
        const { container } = render(<LogLine line="scanning the library" searchTerm="libr" />);

        const marks = container.querySelectorAll('mark');
        expect(marks).toHaveLength(1);
        expect(marks[0]).toHaveTextContent('libr');
    });
});
