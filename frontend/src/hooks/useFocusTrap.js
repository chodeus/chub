import { useEffect, useRef } from 'react';

/**
 * Focusable element selector query
 * Includes all interactive elements that can receive keyboard focus
 */
const FOCUSABLE_SELECTOR = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
].join(', ');

// Newest last: only the top trap acts, so stacked dialogs don't fight over focus.
const activeTraps = [];

/** True when `container` is the most recently activated trap. */
export const isTopFocusTrap = container => activeTraps[activeTraps.length - 1] === container;

/**
 * useFocusTrap - Trap keyboard focus within a container element
 *
 * Manages focus behavior for modal dialogs and other overlay components:
 * - Stores original focused element for restoration on deactivation
 * - Focuses first focusable element when activated
 * - TAB cycles forward through focusable elements (wraps to beginning)
 * - Shift+TAB cycles backward through focusable elements (wraps to end)
 * - Restores focus to original element when deactivated
 * - Handles dynamic content with MutationObserver
 *
 * @example
 * const containerRef = useRef(null);
 * useFocusTrap(containerRef, isModalOpen);
 *
 * return (
 *   <div ref={containerRef} role="dialog">
 *     <button>First focusable</button>
 *     <input type="text" />
 *     <button>Last focusable</button>
 *   </div>
 * );
 *
 * @param {React.RefObject} containerRef - Reference to container element to trap focus within
 * @param {boolean} isActive - Whether focus trap is currently active
 * @returns {void}
 */
export const useFocusTrap = (containerRef, isActive) => {
    const previousFocusRef = useRef(null);
    const observerRef = useRef(null);

    useEffect(() => {
        if (!isActive || !containerRef.current) return;

        const container = containerRef.current;

        // Store currently focused element for restoration
        previousFocusRef.current = document.activeElement;
        activeTraps.push(container);
        const isTopTrap = () => isTopFocusTrap(container);

        // Hidden and inert matches satisfy the selector but silently refuse focus.
        // NOT getClientRects(): jsdom has no layout, so it reports 0 for everything.
        const getFocusableElements = () =>
            Array.from(container.querySelectorAll(FOCUSABLE_SELECTOR)).filter(element => {
                const style = window.getComputedStyle(element);
                return (
                    style.display !== 'none' &&
                    style.visibility !== 'hidden' &&
                    !element.closest('[inert], [aria-hidden="true"], [hidden]')
                );
            });

        // Falls back to the container, which needs tabIndex={-1} to take focus.
        (getFocusableElements()[0] ?? container).focus();

        /**
         * Handle TAB and Shift+TAB key navigation
         * Cycles through focusable elements with wrapping
         * @param {KeyboardEvent} event - Keyboard event
         */
        const handleKeyDown = event => {
            if (event.key !== 'Tab' || !isTopTrap()) return;

            const focusableElements = getFocusableElements();
            const lastIndex = focusableElements.length - 1;
            const index = focusableElements.indexOf(document.activeElement);
            const outside = !container.contains(document.activeElement);

            // index -1 = focus on the container itself or outside it; an empty list swallows Tab.
            if (event.shiftKey ? index <= 0 : index === lastIndex || outside) {
                event.preventDefault();
                (focusableElements[event.shiftKey ? lastIndex : 0] ?? container).focus();
            }
        };

        /**
         * Handle dynamic content changes
         * Refocuses container if active element is removed
         */
        const handleMutation = () => {
            const focusableElements = getFocusableElements();
            const activeElement = document.activeElement;

            // If focused element was removed, focus first available element or the container
            if (isTopTrap() && !container.contains(activeElement)) {
                (focusableElements[0] ?? container).focus();
            }
        };

        // Set up MutationObserver for dynamic content
        observerRef.current = new MutationObserver(handleMutation);
        observerRef.current.observe(container, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['disabled', 'tabindex'],
        });

        // On document: a click on dialog text drops focus to <body>, where the container never sees Tab.
        document.addEventListener('keydown', handleKeyDown);

        // Cleanup function
        return () => {
            document.removeEventListener('keydown', handleKeyDown);
            const wasTopTrap = isTopTrap();
            activeTraps.splice(activeTraps.indexOf(container), 1);

            if (observerRef.current) {
                observerRef.current.disconnect();
                observerRef.current = null;
            }

            // Only the top trap hands focus back; an older one closing underneath would pull it out.
            if (
                wasTopTrap &&
                previousFocusRef.current &&
                document.body.contains(previousFocusRef.current)
            ) {
                previousFocusRef.current.focus();
            }

            previousFocusRef.current = null;
        };
    }, [containerRef, isActive]);
};

export default useFocusTrap;
