/**
 * AI capability gating for the CL2K maker.
 *
 * `aiUnavailableReason` mirrors the backend's text_removal.unavailable_reason()
 * case for case; if the two drift, the UI offers buttons the server rejects.
 * Detection is narrower still — /detect-text takes the LaMa sidecar only — so it
 * needs its own gate rather than riding on the erase one.
 *
 * `readFileAsDataURL` is the page's one FileReader wrapper: every upload/import
 * awaits it, so a read that neither resolves nor rejects hangs that flow's spinner.
 */
import { aiUnavailableReason, lamaDetectReady, readFileAsDataURL } from './Cl2kMakerPage.jsx';

const LAMA = { ai_provider: 'lama_sidecar', ai_endpoint: 'http://lama-sidecar:8418' };
const OPENAI = { ai_provider: 'openai', api_key: 'sk-proj-xxx' };

describe('aiUnavailableReason', () => {
    it('clears a fully configured provider', () => {
        expect(aiUnavailableReason(LAMA)).toBeNull();
        expect(aiUnavailableReason(OPENAI)).toBeNull();
    });

    it('blocks a provider that is missing the field it needs', () => {
        expect(aiUnavailableReason({ ai_provider: 'lama_sidecar' })).toMatch(/Endpoint/);
        expect(aiUnavailableReason({ ai_provider: 'openai' })).toMatch(/API key/);
    });

    it('blocks none, an absent config, and a dropped provider', () => {
        expect(aiUnavailableReason({ ai_provider: 'none' })).toMatch(/none/);
        expect(aiUnavailableReason(undefined)).toMatch(/none/);
        // 'huggingface' was removed upstream; the backend rejects it, so must we.
        expect(aiUnavailableReason({ ai_provider: 'huggingface' })).toMatch(/Unknown/);
    });
});

describe('lamaDetectReady', () => {
    it('is true only for a configured sidecar', () => {
        expect(lamaDetectReady(LAMA)).toBe(true);
    });

    it('is false for OpenAI, which has no detect endpoint', () => {
        expect(lamaDetectReady(OPENAI)).toBe(false);
    });

    it('is false for a sidecar with no endpoint, none, and unknown providers', () => {
        expect(lamaDetectReady({ ai_provider: 'lama_sidecar' })).toBe(false);
        expect(lamaDetectReady({ ai_provider: 'none' })).toBe(false);
        expect(lamaDetectReady({ ai_provider: 'huggingface' })).toBe(false);
        expect(lamaDetectReady(undefined)).toBe(false);
    });
});

describe('readFileAsDataURL', () => {
    it('resolves the data URL for a readable blob', async () => {
        const blob = new Blob(['hello'], { type: 'text/plain' });
        await expect(readFileAsDataURL(blob)).resolves.toMatch(/^data:text\/plain;base64,/);
    });

    it('rejects instead of hanging when the read fails', async () => {
        // jsdom's FileReader reads any Blob, so drive the failure through the
        // error event the wrapper exists to catch.
        const reader = { readAsDataURL: null, error: new Error('boom') };
        const RealFileReader = globalThis.FileReader;
        globalThis.FileReader = function () {
            reader.readAsDataURL = () => queueMicrotask(() => reader.onerror());
            return reader;
        };
        try {
            await expect(readFileAsDataURL(new Blob(['x']))).rejects.toThrow('boom');
        } finally {
            globalThis.FileReader = RealFileReader;
        }
    });

    it('rejects on an aborted read', async () => {
        const reader = { readAsDataURL: null, error: null };
        const RealFileReader = globalThis.FileReader;
        globalThis.FileReader = function () {
            reader.readAsDataURL = () => queueMicrotask(() => reader.onabort());
            return reader;
        };
        try {
            await expect(readFileAsDataURL(new Blob(['x']))).rejects.toThrow(/cancelled/);
        } finally {
            globalThis.FileReader = RealFileReader;
        }
    });
});
