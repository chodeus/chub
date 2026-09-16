import { render, screen } from '@testing-library/react';
import SegmentedControl from './SegmentedControl.jsx';

const options = [
    { value: 'all', label: 'All' },
    { value: 'movies', label: 'Movies' },
];

describe('SegmentedControl', () => {
    it('exposes a radiogroup rather than a tablist', () => {
        render(<SegmentedControl options={options} value="all" onChange={() => {}} />);

        // tablist implies a tabpanel, and no segment owns one.
        expect(screen.getByRole('radiogroup')).toBeInTheDocument();
        expect(screen.queryByRole('tablist')).toBeNull();
        expect(screen.getAllByRole('radio')).toHaveLength(2);
    });

    it('marks the selected segment with aria-checked', () => {
        render(<SegmentedControl options={options} value="movies" onChange={() => {}} />);

        expect(screen.getByRole('radio', { name: 'Movies' })).toHaveAttribute(
            'aria-checked',
            'true'
        );
        expect(screen.getByRole('radio', { name: 'All' })).toHaveAttribute('aria-checked', 'false');
    });

    it('labels the group when given one', () => {
        render(
            <SegmentedControl
                options={options}
                value="all"
                onChange={() => {}}
                ariaLabel="Media type"
            />
        );

        expect(screen.getByRole('radiogroup', { name: 'Media type' })).toBeInTheDocument();
    });
});
