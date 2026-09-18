/**
 * downloadBlob must defer the object-URL revoke — revoking synchronously after
 * the anchor click cancels the in-flight download in WebKit.
 */
import { downloadBlob } from './download.js';

const OBJECT_URL = 'blob:http://localhost/abc-123';

describe('downloadBlob', () => {
    let revoke;

    beforeEach(() => {
        vi.useFakeTimers();
        // jsdom implements neither.
        URL.createObjectURL = () => OBJECT_URL;
        revoke = vi.fn();
        URL.revokeObjectURL = revoke;
    });

    afterEach(() => {
        vi.useRealTimers();
        delete URL.createObjectURL;
        delete URL.revokeObjectURL;
    });

    it('clicks an in-document anchor carrying the object URL and filename', () => {
        let seen = null;
        // Stubbed so jsdom doesn't attempt a real navigation to the blob URL.
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
            seen = {
                href: this.href,
                download: this.download,
                inDocument: document.body.contains(this),
            };
        });

        downloadBlob(new Blob(['payload']), 'chub-export.json');

        expect(seen).toEqual({
            href: OBJECT_URL,
            download: 'chub-export.json',
            inDocument: true,
        });
        expect(document.querySelector('a[download]')).toBeNull();
    });

    it('does not revoke the object URL until the deferred timer fires', () => {
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

        downloadBlob(new Blob(['payload']), 'chub-export.json');
        expect(revoke).not.toHaveBeenCalled();

        vi.advanceTimersByTime(999);
        expect(revoke).not.toHaveBeenCalled();

        vi.advanceTimersByTime(1);
        expect(revoke).toHaveBeenCalledWith(OBJECT_URL);
    });

    it('still cleans up when the click throws', () => {
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {
            throw new Error('blocked');
        });

        expect(() => downloadBlob(new Blob(['payload']), 'chub-export.json')).toThrow('blocked');
        expect(document.querySelector('a[download]')).toBeNull();
        vi.runAllTimers();
        expect(revoke).toHaveBeenCalledWith(OBJECT_URL);
    });
});
