/** Guards the reveal race: a secret arriving after the user types must not overwrite the edit. */
import { useState } from 'react';
import { act, render, screen, fireEvent } from '@testing-library/react';

const api = vi.hoisted(() => ({ resolve: null, reject: null }));

vi.mock('../../../utils/api', async importOriginal => ({
    ...(await importOriginal()),
    configAPI: {
        revealSecret: () =>
            new Promise((res, rej) => {
                api.resolve = () => res({ data: { value: 'real-secret' } });
                api.reject = () => rej(new Error('reveal failed'));
            }),
    },
}));

const { PasswordField } = await import('./PasswordField.jsx');

const field = { key: 'apikey', label: 'API Key', secretPath: 'tmdb.apikey' };

function Harness({ onChange, secretPath = 'tmdb.apikey' }) {
    const [value, setValue] = useState('********');
    return (
        <PasswordField
            field={{ ...field, secretPath }}
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
        await act(async () => {
            api.resolve();
        });

        expect(onChange).toHaveBeenCalledWith('typed');
        expect(screen.getByLabelText('API Key')).toHaveValue('typed');
    });

    it('ignores a reveal that fails after the user starts typing', async () => {
        const onChange = vi.fn();
        render(<Harness onChange={onChange} />);

        fireEvent.click(screen.getByRole('button', { name: 'Show password' }));
        fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'typed' } });
        await act(async () => {
            api.reject();
        });

        expect(onChange).toHaveBeenCalledWith('typed');
        expect(screen.queryByText('Could not reveal secret')).toBeNull();
    });

    it('drops a pending reveal when the secret identity changes', async () => {
        const { rerender } = render(<Harness onChange={() => {}} secretPath="tmdb.apikey" />);
        fireEvent.click(screen.getByRole('button', { name: 'Show password' }));

        rerender(<Harness onChange={() => {}} secretPath="plex.token" />);
        await act(async () => {
            api.resolve();
        });

        expect(screen.getByLabelText('API Key')).toHaveValue('********');
    });
});
