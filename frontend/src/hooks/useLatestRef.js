import { useLayoutEffect, useRef } from 'react';

/** Ref tracking the latest `value` from its commit on (a passive effect lags): one closed over is stale after an `await`. */
export function useLatestRef(value) {
    const ref = useRef(value);
    useLayoutEffect(() => {
        ref.current = value;
    }, [value]);
    return ref;
}
