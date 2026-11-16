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

    const okResponse = (text, headers) =>
        vi.fn(async () => ({
            ok: true,
            status: 200,
            text: async () => text,
            headers: new Headers(headers),
        }));

    it('returns a genuinely empty file as empty text', async () => {
        vi.stubGlobal(
            'fetch',
            okResponse('', {
                'X-Log-Offset': '0',
                'X-Log-Id': '5:e3b0c44298fc',
                'X-Log-Start': '0',
                'X-Log-Reset': '1',
            })
        );

        await expect(logsAPI.fetchLogContent('mod', 'a.log')).resolves.toMatchObject({ text: '' });
    });

    it('sends the last offset, id and start, and reads the next ones from the headers', async () => {
        const fetchMock = okResponse('two\n', {
            'X-Log-Offset': '46',
            'X-Log-Id': '12:ab',
            'X-Log-Start': '7',
            'X-Log-Reset': '0',
        });
        vi.stubGlobal('fetch', fetchMock);

        const read = await logsAPI.fetchLogContent('mod', 'a.log', undefined, {
            offset: 42,
            id: '12:ab',
            start: 7,
        });

        expect(fetchMock.mock.calls[0][0]).toBe('/api/logs/mod/a.log?offset=42&id=12%3Aab&start=7');
        expect(read).toEqual({ text: 'two\n', offset: 46, id: '12:ab', start: 7, reset: false });
    });

    it('rejects a reply with no offset instead of starting over on every poll', async () => {
        vi.stubGlobal('fetch', okResponse('whole file', {}));

        await expect(logsAPI.fetchLogContent('mod', 'a.log')).rejects.toThrow('X-Log-Offset');
    });

    it('rejects a reply with no view start instead of guessing the top of the file', async () => {
        vi.stubGlobal(
            'fetch',
            okResponse('two\n', { 'X-Log-Offset': '4', 'X-Log-Id': '1:a', 'X-Log-Reset': '1' })
        );

        await expect(logsAPI.fetchLogContent('mod', 'a.log')).rejects.toThrow(
            'Log response has no X-Log-Start header'
        );
    });

    it.each(['X-Log-Id', 'X-Log-Reset'])(
        'rejects a reply with no %s instead of guessing it',
        async name => {
            const headers = {
                'X-Log-Offset': '4',
                'X-Log-Id': '1:a',
                'X-Log-Start': '0',
                'X-Log-Reset': '1',
            };
            delete headers[name];
            vi.stubGlobal('fetch', okResponse('two\n', headers));

            await expect(logsAPI.fetchLogContent('mod', 'a.log')).rejects.toThrow(
                `Log response has no ${name} header`
            );
        }
    );

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
