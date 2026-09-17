import { render, screen } from '@testing-library/react';
import Toggle from './Toggle.jsx';

describe('Toggle', () => {
    it('uses the theme border token when off, not a frozen dark colour', () => {
        render(<Toggle checked={false} onChange={() => {}} label="Notify me" />);

        // A literal #2a3052 is the dark theme's --border, so it stayed dark in light mode.
        expect(screen.getByRole('switch')).toHaveStyle({ background: 'var(--border)' });
    });

    it('fills with the brand colour when on', () => {
        render(<Toggle checked onChange={() => {}} label="Notify me" />);

        expect(screen.getByRole('switch')).toHaveStyle({ background: 'var(--primary)' });
    });

    it('takes its accessible name from label', () => {
        render(<Toggle checked={false} onChange={() => {}} label="Notify me" />);

        expect(screen.getByRole('switch', { name: 'Notify me' })).toBeInTheDocument();
    });
});
