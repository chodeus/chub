/** Guards the autofill opt-out — a manager must not offer the saved CHUB login for secrets. */
import { render, screen } from '@testing-library/react';

vi.mock('../../../utils/api', () => ({ configAPI: { revealSecret: vi.fn() } }));

const { PasswordField } = await import('./PasswordField.jsx');

const field = { key: 'api_key', label: 'API Key' };

describe('PasswordField', () => {
    it('opts out of credential autofill', () => {
        render(<PasswordField field={field} value="" onChange={() => {}} />);
        const input = screen.getByLabelText('API Key');

        expect(input).toHaveAttribute('type', 'password');
        expect(input).toHaveAttribute('autocomplete', 'new-password');
        expect(input).toHaveAttribute('data-1p-ignore');
        expect(input).toHaveAttribute('data-lpignore', 'true');
        expect(input).toHaveAttribute('data-bwignore');
        expect(input).toHaveAttribute('data-form-type', 'other');
    });
});
