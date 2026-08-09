/**
 * AI capability gating for the CL2K maker.
 *
 * `aiUnavailableReason` mirrors the backend's text_removal.unavailable_reason()
 * case for case; if the two drift, the UI offers buttons the server rejects.
 * Detection is narrower still — /detect-text takes the LaMa sidecar only — so it
 * needs its own gate rather than riding on the erase one.
 */
import { aiUnavailableReason, lamaDetectReady } from './Cl2kMakerPage.jsx';

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
