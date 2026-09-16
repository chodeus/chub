/** Guards the reveal race: a secret arriving after the user types must not overwrite the edit. */
import { useState } from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const api = vi.hoisted(() => ({ resolve: null }));

vi.mock('../../../utils/api', async importOriginal => ({
    ...(await importOriginal()),
    configAPI: {
        revealSecret: () =>
            new Promise(res => {
                api.resolve = () => res({ data: { value: 'real-secret' } });
            }),
    },
}));

const { PasswordField } = await import('./PasswordField.jsx');

const field = { key: 'apikey', label: 'API Key', secretPath: 'tmdb.apikey' };

function Harness({ onChange }) {
    const [value, setValue] = useState('********');
    return (
        <PasswordField
            field={field}
            value={value}
            onChange={next => {
                setValue(next);
                onChange(next);
            }}
        />
    );
}

describe('PasswordField', () => {
    it('ignores a reveal that resolves after the user starts typing', async () => {
        const onChange = vi.fn();
        render(<Harness onChange={onChange} />);

        fireEvent.click(screen.getByRole('button', { name: 'Show password' }));
        fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'typed' } });
        api.resolve();

        await waitFor(() => expect(onChange).toHaveBeenCalledWith('typed'));
        expect(screen.getByLabelText('API Key')).toHaveValue('typed');
    });
});
