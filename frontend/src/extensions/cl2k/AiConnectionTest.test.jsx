import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// The factory wraps the spy rather than passing it: vitest.config sets
// mockReset, which would strip an implementation handed over directly.
const mockPost = vi.fn();
vi.mock('../../utils/api/core', () => ({ apiCore: { post: (...args) => mockPost(...args) } }));

const toast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() };
vi.mock('../../contexts/ToastContext.jsx', () => ({ useToast: () => toast }));

const { Cl2kAiTestField } = await import('./AiConnectionTest.jsx');

const withProvider = { cl2k_maker: { ai_provider: 'openai' } };
const button = () => screen.getByRole('button', { name: /Test connection/ });

describe('Cl2kAiTestField', () => {
    it('aborts an in-flight connection test when the field unmounts', async () => {
        let signal;
        mockPost.mockImplementation((url, body, options) => {
            signal = options?.signal;
            return new Promise(() => {});
        });
        const { unmount } = render(<Cl2kAiTestField rootConfig={withProvider} />);

        fireEvent.click(button());
        await waitFor(() => expect(signal).toBeDefined());
        expect(signal.aborted).toBe(false);

        unmount();
        expect(signal.aborted).toBe(true);
    });

    it('stays silent when the request is aborted', async () => {
        mockPost.mockRejectedValue(Object.assign(new Error('aborted'), { name: 'AbortError' }));
        render(<Cl2kAiTestField rootConfig={withProvider} />);

        fireEvent.click(button());

        // An abort is the component's own doing: reporting it would replace a
        // stray success toast with a stray error one.
        await waitFor(() => expect(mockPost).toHaveBeenCalled());
        expect(toast.error).not.toHaveBeenCalled();
        expect(toast.success).not.toHaveBeenCalled();
    });

    it('still reports a real failure', async () => {
        mockPost.mockRejectedValue(new Error('no API key'));
        render(<Cl2kAiTestField rootConfig={withProvider} />);

        fireEvent.click(button());

        await waitFor(() => expect(toast.error).toHaveBeenCalledWith('no API key'));
    });

    it('is disabled until a provider is chosen', () => {
        render(<Cl2kAiTestField rootConfig={{}} />);

        expect(button()).toBeDisabled();
    });
});
