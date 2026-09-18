import { render, screen, fireEvent } from '@testing-library/react';
import { BreakdownTabs } from './MediaStatsPage.jsx';

// by_tags is present but empty, so it must not earn a tab.
const stats = {
    by_status: [{ status: 'Downloaded', count: 5 }],
    by_tags: [],
    by_genre: [{ genre: 'Action', count: 3 }],
    by_decade: [{ decade: '1990s', count: 2 }],
};

// Each tab's accessible name is its label followed by the bucket's item count.
const radio = label => screen.getByRole('radio', { name: new RegExp(`^${label}`) });

describe('BreakdownTabs', () => {
    it('shows a radiogroup holding only the populated breakdowns', () => {
        render(<BreakdownTabs stats={stats} />);

        expect(screen.getByRole('radiogroup', { name: 'Breakdown' })).toBeInTheDocument();
        expect(screen.getAllByRole('radio')).toHaveLength(3);
        expect(screen.queryByRole('radio', { name: /^Tags/ })).toBeNull();
    });

    it('renders nothing when no breakdown has data', () => {
        const { container } = render(<BreakdownTabs stats={{ by_status: [], by_genre: [] }} />);

        expect(container).toBeEmptyDOMElement();
    });

    it('keeps only the active tab in the tab order', () => {
        render(<BreakdownTabs stats={stats} />);

        expect(radio('Status')).toHaveAttribute('tabindex', '0');
        expect(radio('Genre')).toHaveAttribute('tabindex', '-1');
        expect(radio('Decade')).toHaveAttribute('tabindex', '-1');
    });

    it('selects and focuses the next tab on ArrowRight', () => {
        render(<BreakdownTabs stats={stats} />);

        fireEvent.keyDown(radio('Status'), { key: 'ArrowRight' });

        // A radiogroup selects on arrow, not just moves focus.
        expect(radio('Genre')).toHaveAttribute('aria-checked', 'true');
        expect(document.activeElement).toBe(radio('Genre'));
    });

    it('wraps to the last tab on ArrowLeft from the first', () => {
        render(<BreakdownTabs stats={stats} />);

        fireEvent.keyDown(radio('Status'), { key: 'ArrowLeft' });

        expect(radio('Decade')).toHaveAttribute('aria-checked', 'true');
        expect(document.activeElement).toBe(radio('Decade'));
    });

    it('jumps to the first and last tabs with Home and End', () => {
        render(<BreakdownTabs stats={stats} />);

        fireEvent.keyDown(radio('Status'), { key: 'End' });
        expect(radio('Decade')).toHaveAttribute('aria-checked', 'true');

        fireEvent.keyDown(radio('Decade'), { key: 'Home' });
        expect(radio('Status')).toHaveAttribute('aria-checked', 'true');
    });

    it('ignores keys that are not part of the contract', () => {
        render(<BreakdownTabs stats={stats} />);

        fireEvent.keyDown(radio('Status'), { key: 'a' });

        expect(radio('Status')).toHaveAttribute('aria-checked', 'true');
    });
});
