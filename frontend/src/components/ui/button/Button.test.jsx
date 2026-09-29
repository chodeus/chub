import { fireEvent, render, screen } from '@testing-library/react';
import { Link, MemoryRouter, Route, Routes } from 'react-router';
import { Button } from './Button.jsx';

describe('Button', () => {
    it('renders a native button by default', () => {
        render(<Button>Save</Button>);
        expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('type', 'button');
    });

    it('renders as a router link without button-only attributes', () => {
        render(
            <MemoryRouter>
                <Button as={Link} to="/settings/modules" icon="add">
                    Add source
                </Button>
            </MemoryRouter>
        );
        const link = screen.getByRole('link', { name: 'Add source' });
        expect(link).toHaveAttribute('href', '/settings/modules');
        expect(link).not.toHaveAttribute('type');
    });

    it('keeps a disabled link from navigating', () => {
        render(
            <MemoryRouter initialEntries={['/start']}>
                <Routes>
                    <Route
                        path="/start"
                        element={
                            <Button as={Link} to="/next" disabled>
                                Go
                            </Button>
                        }
                    />
                    <Route path="/next" element={<p>Arrived</p>} />
                </Routes>
            </MemoryRouter>
        );
        const link = screen.getByRole('link', { name: 'Go' });
        expect(link).toHaveAttribute('aria-disabled', 'true');
        fireEvent.click(link);
        expect(screen.queryByText('Arrived')).not.toBeInTheDocument();
    });
});
