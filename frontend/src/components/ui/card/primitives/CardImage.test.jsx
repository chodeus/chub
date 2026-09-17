import { render, screen, fireEvent } from '@testing-library/react';
import { CardImage } from './CardImage.jsx';

describe('CardImage', () => {
    it('shows the fallback when an image fails', () => {
        render(<CardImage src="/a.jpg" alt="a" />);

        fireEvent.error(screen.getByAltText('a'));

        expect(screen.getByText('Failed to load image')).toBeInTheDocument();
    });

    it('recovers when the src changes after a failure', () => {
        const { rerender } = render(<CardImage src="/a.jpg" alt="a" />);
        fireEvent.error(screen.getByAltText('a'));
        expect(screen.getByText('Failed to load image')).toBeInTheDocument();

        rerender(<CardImage src="/b.jpg" alt="b" />);

        // Without the reset, one broken image leaves the fallback up for every later src.
        expect(screen.getByAltText('b')).toBeInTheDocument();
        expect(screen.queryByText('Failed to load image')).toBeNull();
    });
});
