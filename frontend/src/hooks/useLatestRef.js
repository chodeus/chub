import { useEffect, useRef } from 'react';

/** Ref tracking the latest `value`: one closed over is stale after an `await`. */
export function useLatestRef(value) {
    const ref = useRef(value);
    useEffect(() => {
        ref.current = value;
    }, [value]);
    return ref;
}
