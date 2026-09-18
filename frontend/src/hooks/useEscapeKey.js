import { useEffect } from 'react';

/** Calls `onEscape` on ESC while `isActive`. Listener is document-level. */
export const useEscapeKey = (onEscape, isActive) => {
    useEffect(() => {
        if (!isActive) return;

        const handleEscape = event => {
            if (event.key === 'Escape') {
                onEscape();
            }
        };

        document.addEventListener('keydown', handleEscape);

        return () => {
            document.removeEventListener('keydown', handleEscape);
        };
    }, [onEscape, isActive]);
};

export default useEscapeKey;
