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
    const [token, setToken] = useState(streamTokenSnapshot);
    useEffect(() => {
        ensureStreamToken();
        return subscribeStreamToken(() => setToken(streamTokenSnapshot()));
    }, []);
    return token;
}

export default useStreamToken;
