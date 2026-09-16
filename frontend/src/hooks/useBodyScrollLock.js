import { useEffect } from 'react';

// Shared across every lock: per-instance state would let the first modal to close
// restore scrolling while another is still open, or leave the body locked with none.
let lockCount = 0;
let savedOverflow = '';
let savedScrollY = 0;

/** Locks body scroll while `isLocked`; concurrent locks are reference-counted. */
export const useBodyScrollLock = isLocked => {
    useEffect(() => {
        if (!isLocked) return;

        // Only the outermost lock touches the body; the rest just raise the count.
        if (lockCount === 0) {
            savedScrollY = window.scrollY;
            savedOverflow = document.body.style.overflow;
            document.body.style.overflow = 'hidden';
        }
        lockCount += 1;

        // iOS Safari fix: prevent bounce scrolling
        const preventTouchMove = event => {
            // Allow scrolling within modal elements
            if (event.target.closest('[role="dialog"]')) {
                return;
            }
            event.preventDefault();
        };

        // Only prevent touch move on iOS devices
        const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
        if (isIOS) {
            document.addEventListener('touchmove', preventTouchMove, { passive: false });
        }

        // Cleanup function
        return () => {
            lockCount = Math.max(0, lockCount - 1);
            if (lockCount === 0) {
                document.body.style.overflow = savedOverflow;
                window.scrollTo(0, savedScrollY);
            }

            if (isIOS) {
                document.removeEventListener('touchmove', preventTouchMove);
            }
        };
    }, [isLocked]);
};

export default useBodyScrollLock;
