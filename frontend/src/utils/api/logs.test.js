/** Guards that log request failures reject instead of rendering as empty results. */
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('./core.js', () => ({
    apiCore: { get: vi.fn() },
}));

const { apiCore } = await import('./core.js');
const { logsAPI } = await import('./logs.js');

afterEach(() => {
    vi.unstubAllGlobals();
    apiCore.get.mockReset();
});

describe('logsAPI.fetchLogFiles', () => {
    it('rejects instead of reporting an empty file list', async () => {
        apiCore.get.mockRejectedValue(new Error('backend down'));

        await expect(logsAPI.fetchLogFiles('border_replacerr')).rejects.toThrow('backend down');
    });

    it('still returns an empty list for a module with no files', async () => {
        apiCore.get.mockResolvedValue({ data: { files: [] } });

        await expect(logsAPI.fetchLogFiles('border_replacerr')).resolves.toEqual([]);
    });

    it('still short-circuits without a module name', async () => {
        await expect(logsAPI.fetchLogFiles('')).resolves.toEqual([]);
        expect(apiCore.get).not.toHaveBeenCalled();
    });
});

describe('logsAPI.fetchLogContent', () => {
    it('rejects on a non-OK response instead of returning empty text', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => ({ ok: false, status: 500, text: async () => '' }))
        );

        await expect(logsAPI.fetchLogContent('mod', 'a.log')).rejects.toThrow('status 500');
    });

    it('rejects on a network failure instead of returning empty text', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => {
                throw new TypeError('network');
            })
        );

        await expect(logsAPI.fetchLogContent('mod', 'a.log')).rejects.toThrow('network');
    });

    it('returns a genuinely empty file as empty text', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => ({ ok: true, status: 200, text: async () => '' }))
        );

        await expect(logsAPI.fetchLogContent('mod', 'a.log')).resolves.toBe('');
    });

    it('still rethrows an AbortError for a cancelled request', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => {
                const err = new Error('aborted');
                err.name = 'AbortError';
                throw err;
            })
        );

        await expect(logsAPI.fetchLogContent('mod', 'a.log')).rejects.toMatchObject({
            name: 'AbortError',
        });
    });
});
