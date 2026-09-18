import { render, screen, fireEvent } from '@testing-library/react';
import { ServiceIcon } from './ServiceIcon.jsx';

describe('ServiceIcon', () => {
    it('hides the icon when the CDN image fails', () => {
        const { container } = render(<ServiceIcon service="plex" />);

        fireEvent.error(screen.getByAltText('plex icon'));

        expect(container).toBeEmptyDOMElement();
    });

    it('shows the icon again when the service changes after a failure', () => {
        const { container, rerender } = render(<ServiceIcon service="plex" />);
        fireEvent.error(screen.getByAltText('plex icon'));
        expect(container).toBeEmptyDOMElement();

        rerender(<ServiceIcon service="radarr" />);

        // Hiding the node via style.display left it hidden forever once React reused it.
        expect(screen.getByAltText('radarr icon')).toBeInTheDocument();
    });
});
