/**
 * Every secret in Settings (*arr API keys, Plex tokens, webhook secrets) renders
 * through PasswordField. Browsers ignore autocomplete="off" on type=password, so
 * without an explicit opt-out a password manager offers the saved CHUB login for
 * these fields — one stray accept silently writes the wrong secret into config.
 */
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
