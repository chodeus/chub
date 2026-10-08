import { renderHook, act } from '@testing-library/react';

vi.mock('../utils/api/streamAuth.js', () => ({
    ensureStreamToken: vi.fn(),
    clearStreamToken: vi.fn(),
}));
vi.mock('../utils/api/core.js', () => ({ apiCore: { clearCache: vi.fn() } }));

const { AuthProvider, useAuth } = await import('./AuthContext.jsx');

const TOKEN_KEY = 'chub-auth-token';
const reply = data => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) });

const mountAuth = async () => {
    let hook;
    await act(async () => {
        hook = renderHook(() => useAuth(), { wrapper: AuthProvider });
    });
    return hook;
};

describe('AuthProvider', () => {
    beforeEach(() => {
        localStorage.clear();
        vi.stubGlobal(
            'fetch',
            vi.fn(url => {
                if (url.includes('/api/auth/status'))
                    return reply({ success: true, data: { configured: true } });
                if (url.includes('/api/setup/status'))
                    return reply({ success: true, data: { completed: true } });
                if (url.includes('/api/auth/login'))
                    return reply({ success: true, data: { token: 't0ken', username: 'dean' } });
                return reply({ success: true, data: {} });
            })
        );
    });

    it('signs the user in and stores the token', async () => {
        const { result } = await mountAuth();

        await act(async () => {
            await result.current.login('dean', 'pw');
        });

        expect(result.current.isAuthenticated).toBe(true);
        expect(result.current.user).toBe('dean');
        expect(localStorage.getItem(TOKEN_KEY)).toBe('t0ken');
    });

    it('still signs the user in when storage refuses the token', async () => {
        // Safari with site data blocked, or an exhausted quota, throws from setItem.
        vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
            throw new DOMException('QuotaExceededError');
        });
        const { result } = await mountAuth();

        await act(async () => {
            await result.current.login('dean', 'pw');
        });

        expect(result.current.isAuthenticated).toBe(true);
        expect(result.current.user).toBe('dean');
    });

    it('sends the bearer to setup completion even when storage refused the token', async () => {
        vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
            throw new DOMException('QuotaExceededError');
        });
        const calls = [];
        vi.stubGlobal(
            'fetch',
            vi.fn((url, init) => {
                calls.push([url, init]);
                if (url.includes('/api/auth/status'))
                    return reply({ success: true, data: { configured: false } });
                if (url.includes('/api/setup/status'))
                    return reply({ success: true, data: { completed: false } });
                if (url.includes('/api/auth/setup'))
                    return reply({ success: true, data: { token: 't0ken', username: 'dean' } });
                return reply({ success: true, data: {} });
            })
        );

        const { result } = await mountAuth();
        await act(async () => {
            await result.current.setup('dean', 'pw');
        });
        await act(async () => {
            await result.current.markSetupComplete();
        });

        // Without the bearer the server flag stays false and the wizard reopens.
        const completion = calls.find(([url]) => url.includes('/api/setup/complete'));
        expect(completion?.[1]?.headers?.Authorization).toBe('Bearer t0ken');
    });

    it('logs out even when storage refuses to drop the token', async () => {
        const { result } = await mountAuth();
        await act(async () => {
            await result.current.login('dean', 'pw');
        });
        vi.spyOn(localStorage, 'removeItem').mockImplementation(() => {
            throw new DOMException('SecurityError');
        });

        act(() => {
            result.current.logout();
        });

        expect(result.current.isAuthenticated).toBe(false);
    });

    const stubDisable = response => {
        const calls = [];
        const base = fetch;
        vi.stubGlobal(
            'fetch',
            vi.fn((url, init) => {
                if (!url.includes('/api/auth/disable')) return base(url, init);
                calls.push(init);
                return response;
            })
        );
        return calls;
    };

    it('turns the login off with the password and the session bearer', async () => {
        const { result } = await mountAuth();
        await act(async () => {
            await result.current.login('dean', 'pw');
        });
        const calls = stubDisable(reply({ success: true }));

        await act(async () => {
            await result.current.disableAuth('pw');
        });

        expect(calls).toHaveLength(1);
        expect(calls[0].headers.Authorization).toBe('Bearer t0ken');
        expect(JSON.parse(calls[0].body)).toEqual({ password: 'pw' });
        expect(result.current.isAuthenticated).toBe(false);
        expect(result.current.authConfigured).toBe(false);
        expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    });

    it('keeps the session when the password is wrong', async () => {
        const { result } = await mountAuth();
        await act(async () => {
            await result.current.login('dean', 'pw');
        });
        stubDisable(
            Promise.resolve({
                ok: false,
                status: 403,
                json: () => Promise.resolve({ success: false, message: 'Incorrect password' }),
            })
        );

        let thrown;
        await act(async () => {
            await result.current.disableAuth('nope').catch(err => {
                thrown = err;
            });
        });

        expect(thrown?.message).toBe('Incorrect password');
        expect(result.current.isAuthenticated).toBe(true);
        expect(result.current.authConfigured).toBe(true);
    });
});
