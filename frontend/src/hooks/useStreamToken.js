import { useState, useEffect } from 'react';
import {
    subscribeStreamToken,
    streamTokenSnapshot,
    ensureStreamToken,
} from '../utils/api/streamAuth.js';

/**
 * Subscribe a component to the current stream token. Ensures the token is
 * fetched, and re-renders the component whenever it's minted/refreshed — so any
 * `<img src>` it builds (via getThumbnailUrl / getPosterUrl / getPreviewUrl)
 * gets rebuilt WITH the token instead of rendering token-less (401) during the
 * initial fetch race or a refresh. Call it once in any page that renders a
 * poster/thumbnail grid; the return value can be ignored.
 */
export function useStreamToken() {
    // Re-render on EVERY stream-auth change, not just token-value changes: when
    // auth is not configured the token stays '' permanently, so tracking the
    // token value alone would never re-render the grid to swap the blank
    // placeholder for a real (token-less) image URL. A tick forces the re-render
    // once the auth state resolves.
    const [, setTick] = useState(0);
    useEffect(() => {
        ensureStreamToken();
        return subscribeStreamToken(() => setTick(t => t + 1));
    }, []);
    return streamTokenSnapshot();
}

export default useStreamToken;
