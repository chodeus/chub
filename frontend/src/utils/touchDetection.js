/** Touch detection: reorder arrows on touch devices, drag handles elsewhere. */

import React from 'react';

/** True when the device supports touch input. */
export const isTouchDevice = () => {
    // Check for touch events support
    if ('ontouchstart' in window) {
        return true;
    }

    // Check for touch points
    if (navigator.maxTouchPoints && navigator.maxTouchPoints > 0) {
        return true;
    }

    // Check for msMaxTouchPoints (IE/Edge)
    if (navigator.msMaxTouchPoints && navigator.msMaxTouchPoints > 0) {
        return true;
    }

    // Check for pointer support with fine pointer (non-touch)
    if (window.matchMedia && window.matchMedia('(pointer: fine)').matches) {
        return false;
    }

    // Check for coarse pointer (touch)
    if (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) {
        return true;
    }

    // Fallback: assume non-touch for desktop-like environments
    return false;
};

/** Touch detection that re-renders when pointer capability changes. */
export const useTouchDevice = () => {
    const [isTouch, setIsTouch] = React.useState(isTouchDevice);

    React.useEffect(() => {
        // Update detection if media queries change
        const mediaQueryList = window.matchMedia('(pointer: coarse)');

        const handleChange = () => {
            setIsTouch(isTouchDevice());
        };

        // Listen for media query changes
        if (mediaQueryList.addEventListener) {
            mediaQueryList.addEventListener('change', handleChange);
        } else if (mediaQueryList.addListener) {
            // Fallback for older browsers
            mediaQueryList.addListener(handleChange);
        }

        // Listen for custom touch capability change events (for DevTools simulation)
        const handleTouchCapabilityChange = () => {
            setIsTouch(isTouchDevice());
        };

        window.addEventListener('touchCapabilityChanged', handleTouchCapabilityChange);

        // Cleanup function
        return () => {
            if (mediaQueryList.removeEventListener) {
                mediaQueryList.removeEventListener('change', handleChange);
            } else if (mediaQueryList.removeListener) {
                mediaQueryList.removeListener(handleChange);
            }
            window.removeEventListener('touchCapabilityChanged', handleTouchCapabilityChange);
        };
    }, []);

    return isTouch;
};

/** Picks between touch and non-touch class strings. */
export const touchClasses = (touchClasses = '', nonTouchClasses = '') => {
    return isTouchDevice() ? touchClasses : nonTouchClasses;
};
