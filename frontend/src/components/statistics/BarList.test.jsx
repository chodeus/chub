import { render, screen, fireEvent } from '@testing-library/react';
import { BarList } from './BarList.jsx';

const items = [
    { label: 'Movies', count: 200, pct: 66.7 },
    { label: 'Shows', count: 50, pct: 16.7 },
    { label: 'Others', count: 50, pct: 16.7 },
];

const barWidths = container =>
    [...container.querySelectorAll('.h-full.rounded-full')].map(bar => bar.style.width);

describe('BarList', () => {
    it('scales every bar to the largest count and keeps caller order', () => {
        const { container } = render(<BarList items={items} />);

        expect(barWidths(container)).toEqual(['100%', '25%', '25%']);
        const labels = screen.getAllByTitle(/.+/).map(el => el.getAttribute('title'));
        expect(labels).toEqual(['Movies', 'Shows', 'Others']);
    });

    it('shows the count and, when given, the share', () => {
        render(<BarList items={[{ label: 'Movies', count: 1048, pct: 41.1 }]} />);

        expect(screen.getByText('1,048 · 41.1%')).toBeInTheDocument();
    });

    it('renders a null count as zero instead of throwing', () => {
        const { container } = render(<BarList items={[{ label: 'Empty', count: null }]} />);

        expect(screen.getByText('0')).toBeInTheDocument();
        expect(barWidths(container)).toEqual(['0%']);
    });

    it('caps the rows at maxItems until "Show all" is pressed', () => {
        render(<BarList items={items} maxItems={2} />);

        expect(screen.queryByTitle('Others')).toBeNull();
        fireEvent.click(screen.getByRole('button', { name: 'Show all 3' }));
        expect(screen.getByTitle('Others')).toBeInTheDocument();
    });

    it('turns rows into toggle buttons when onSelect is set', () => {
        const onSelect = vi.fn();
        render(<BarList items={items} onSelect={onSelect} activeLabel="Shows" />);

        const shows = screen.getByRole('button', { name: /^Shows/ });
        expect(shows).toHaveAttribute('aria-pressed', 'true');
        expect(screen.getByRole('button', { name: /^Movies/ })).toHaveAttribute(
            'aria-pressed',
            'false'
        );
        fireEvent.click(shows);
        expect(onSelect).toHaveBeenCalledWith('Shows');
    });
});
