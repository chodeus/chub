import { render, screen, fireEvent } from '@testing-library/react';
import SegmentedControl from './SegmentedControl.jsx';

const options = [
    { value: 'all', label: 'All' },
    { value: 'movies', label: 'Movies' },
];

const renderControl = (props = {}) =>
    render(
        <SegmentedControl
            options={options}
            value="all"
            onChange={() => {}}
            ariaLabel="Media type"
            {...props}
        />
    );

describe('SegmentedControl', () => {
    it('exposes a radiogroup rather than a tablist', () => {
        renderControl();

        // tablist implies a tabpanel, and no segment owns one.
        expect(screen.getByRole('radiogroup', { name: 'Media type' })).toBeInTheDocument();
        expect(screen.queryByRole('tablist')).toBeNull();
        expect(screen.getAllByRole('radio')).toHaveLength(2);
    });

    it('marks the selected segment with aria-checked', () => {
        renderControl({ value: 'movies' });

        expect(screen.getByRole('radio', { name: 'Movies' })).toHaveAttribute(
            'aria-checked',
            'true'
        );
        expect(screen.getByRole('radio', { name: 'All' })).toHaveAttribute('aria-checked', 'false');
    });

    it('keeps only the selected segment in the tab order', () => {
        renderControl({ value: 'movies' });

        expect(screen.getByRole('radio', { name: 'Movies' })).toHaveAttribute('tabindex', '0');
        expect(screen.getByRole('radio', { name: 'All' })).toHaveAttribute('tabindex', '-1');
    });

    it('falls back to the first segment when the value matches no option', () => {
        renderControl({ value: '' });

        expect(screen.getByRole('radio', { name: 'All' })).toHaveAttribute('tabindex', '0');
    });

    it('selects and focuses the next segment on ArrowRight', () => {
        const onChange = vi.fn();
        renderControl({ onChange });

        fireEvent.keyDown(screen.getByRole('radio', { name: 'All' }), { key: 'ArrowRight' });

        // A radiogroup selects on arrow, not just moves focus.
        expect(onChange).toHaveBeenCalledWith('movies');
        expect(document.activeElement).toBe(screen.getByRole('radio', { name: 'Movies' }));
    });

    it('wraps to the last segment on ArrowLeft from the first', () => {
        const onChange = vi.fn();
        renderControl({ onChange });

        fireEvent.keyDown(screen.getByRole('radio', { name: 'All' }), { key: 'ArrowLeft' });

        expect(onChange).toHaveBeenCalledWith('movies');
        expect(document.activeElement).toBe(screen.getByRole('radio', { name: 'Movies' }));
    });

    it('jumps to the first and last segments with Home and End', () => {
        const onChange = vi.fn();
        renderControl({ onChange });

        fireEvent.keyDown(screen.getByRole('radio', { name: 'All' }), { key: 'End' });
        expect(onChange).toHaveBeenLastCalledWith('movies');

        fireEvent.keyDown(screen.getByRole('radio', { name: 'Movies' }), { key: 'Home' });
        expect(onChange).toHaveBeenLastCalledWith('all');
    });

    it('ignores keys that are not part of the contract', () => {
        const onChange = vi.fn();
        renderControl({ onChange });

        fireEvent.keyDown(screen.getByRole('radio', { name: 'All' }), { key: 'a' });

        expect(onChange).not.toHaveBeenCalled();
    });
});
