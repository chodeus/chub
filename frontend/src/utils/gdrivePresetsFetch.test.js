/** Guards the preset fetch: a non-string URL, a bounded external request, the internal route. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./api/core.js', () => ({ apiCore: { get: vi.fn() } }));

const { apiCore } = await import('./api/core.js');
const { fetchGdrivePresets, GDRIVE_PRESETS_FALLBACK_URL } = await import('./gdrivePresets.js');

const presetPayload = [{ name: 'Solen', style: 'CL2K', id: 'abc' }];

beforeEach(() => {
    apiCore.get.mockReset();
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

describe('fetchGdrivePresets', () => {
    it('falls back instead of throwing when the URL is not a string', async () => {
        const fetchMock = vi.fn(async () => ({ ok: true, json: async () => presetPayload }));
        vi.stubGlobal('fetch', fetchMock);

        await expect(fetchGdrivePresets(undefined)).resolves.toEqual([
            { name: 'CL2K Solen', style: 'CL2K', id: 'abc' },
        ]);
        expect(fetchMock).toHaveBeenCalledWith(GDRIVE_PRESETS_FALLBACK_URL, expect.anything());
    });

    it('bounds the external fetch with an abort signal', async () => {
        const fetchMock = vi.fn(async () => ({ ok: true, json: async () => presetPayload }));
        vi.stubGlobal('fetch', fetchMock);

        await fetchGdrivePresets(GDRIVE_PRESETS_FALLBACK_URL);

        const [, options] = fetchMock.mock.calls[0];
        expect(options?.signal).toBeInstanceOf(AbortSignal);
    });

    it('still routes an internal URL through apiCore, untouched', async () => {
        apiCore.get.mockResolvedValueOnce({ data: presetPayload });
        const fetchMock = vi.fn();
        vi.stubGlobal('fetch', fetchMock);

        await expect(fetchGdrivePresets('/api/gdrive-presets')).resolves.toEqual([
            { name: 'CL2K Solen', style: 'CL2K', id: 'abc' },
        ]);
        expect(apiCore.get).toHaveBeenCalledWith('/gdrive-presets', { useCache: false });
        expect(fetchMock).not.toHaveBeenCalled();
    });
});
