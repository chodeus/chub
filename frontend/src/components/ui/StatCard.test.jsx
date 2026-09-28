import { render, screen } from '@testing-library/react';
import { StatCard } from './StatCard.jsx';

describe('StatCard', () => {
    it('formats a numeric value with thousands separators', () => {
        render(<StatCard label="Total Media" value={59203} />);

        expect(screen.getByText('59,203')).toBeInTheDocument();
    });

    it('colours the value from valueColor', () => {
        render(<StatCard label="Missing" value={12} valueColor="warning" />);

        expect(screen.getByText('12')).toHaveClass('text-warning');
    });

    it('keeps the subtext row when there is no subtext, so sibling tiles line up', () => {
        const { container } = render(<StatCard label="Total Media" value={1} />);

        const rows = container.querySelectorAll('p');
        expect(rows).toHaveLength(3);
        expect(rows[2].textContent).toBe(' ');
    });
});
