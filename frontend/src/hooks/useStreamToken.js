import { useState, useEffect } from 'react';
import {
    subscribeStreamToken,
    streamTokenSnapshot,
    ensureStreamToken,
} from '../utils/api/streamAuth.js';

/** Re-renders the caller whenever the stream token is minted or refreshed, so token-bearing image URLs rebuild instead of 401ing. */
export function useStreamToken() {
    // Ticks on every stream-auth change, not just token-value changes: with auth off
    // the token stays '' forever, so watching its value alone would never re-render.
    const [, setTick] = useState(0);
    useEffect(() => {
        ensureStreamToken();
        return subscribeStreamToken(() => setTick(t => t + 1));
    }, []);
    return streamTokenSnapshot();
}

export default useStreamToken;
