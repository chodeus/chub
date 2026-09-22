import { useEffect, useRef } from 'react';

/** Ref that tracks the latest `value`, for reading after an `await`.
 *  A value closed over is the one from that render, so it goes stale while an
 *  async dialog is open and the user changes state behind it. */
export function useLatestRef(value) {
    const ref = useRef(value);
    useEffect(() => {
        ref.current = value;
    }, [value]);
    return ref;
}
