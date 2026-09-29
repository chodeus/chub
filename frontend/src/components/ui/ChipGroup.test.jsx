import { render, screen, fireEvent } from '@testing-library/react';
import ChipGroup from './ChipGroup.jsx';

const options = [
    { value: 'tmdb', label: 'TMDB' },
    { value: 'imdb', label: 'IMDB' },
];

const renderGroup = (props = {}) =>
    render(
        <ChipGroup
            options={options}
            isSelected={v => v === 'tmdb'}
            onToggle={() => {}}
            ariaLabel="Missing fields"
            {...props}
        />
    );

describe('ChipGroup', () => {
    it('names the group and marks selected chips with aria-pressed', () => {
        renderGroup();

        expect(screen.getByRole('group', { name: 'Missing fields' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'TMDB' })).toHaveAttribute(
            'aria-pressed',
            'true'
        );
        expect(screen.getByRole('button', { name: 'IMDB' })).toHaveAttribute(
            'aria-pressed',
            'false'
        );
    });

    it('passes the clicked chip value to onToggle', () => {
        const onToggle = vi.fn();
        renderGroup({ onToggle });

        fireEvent.click(screen.getByRole('button', { name: 'IMDB' }));
        expect(onToggle).toHaveBeenCalledWith('imdb');
    });

    it('ignores clicks while disabled', () => {
        const onToggle = vi.fn();
        renderGroup({ onToggle, disabled: true });

        fireEvent.click(screen.getByRole('button', { name: 'IMDB' }));
        expect(onToggle).not.toHaveBeenCalled();
    });
});

describe('ChipGroup single', () => {
    const renderSingle = (props = {}) =>
        render(
            <ChipGroup
                single
                options={[
                    { value: 'status', label: 'Status', count: 3 },
                    { value: 'genre', label: 'Genre', count: 12 },
                ]}
                isSelected={v => v === 'status'}
                onToggle={() => {}}
                ariaLabel="Breakdown"
                {...props}
            />
        );

    it('is a radiogroup with only the selected chip in the tab order', () => {
        renderSingle();

        expect(screen.getByRole('radiogroup', { name: 'Breakdown' })).toBeInTheDocument();
        const [status, genre] = screen.getAllByRole('radio');
        expect(status).toHaveAttribute('aria-checked', 'true');
        expect(status).toHaveAttribute('tabindex', '0');
        expect(genre).toHaveAttribute('tabindex', '-1');
        expect(genre).toHaveTextContent('12');
    });

    it('selects the next chip on ArrowRight', () => {
        const onToggle = vi.fn();
        renderSingle({ onToggle });

        fireEvent.keyDown(screen.getAllByRole('radio')[0], { key: 'ArrowRight' });
        expect(onToggle).toHaveBeenCalledWith('genre');
    });
});
