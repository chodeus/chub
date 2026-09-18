import { useEffect, useRef } from 'react';

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

/** Cycles TAB within `containerRef` while active, restores the previously focused
 *  element on deactivation, and re-scans via MutationObserver for dynamic content. */
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

        // `display` does not inherit, so walk ancestors; `visibility` does, so the
        // element's own computed value already covers hidden ancestors.
        const isDisplayed = element => {
            for (let node = element; node instanceof Element; node = node.parentElement) {
                if (window.getComputedStyle(node).display === 'none') return false;
            }
            return true;
        };

        // Hidden, inert and disabled matches refuse focus; aria-hidden ones accept it but
        // must not get it. NOT getClientRects(): jsdom has no layout and reports 0 for all.
        const getFocusableElements = () =>
            Array.from(container.querySelectorAll(FOCUSABLE_SELECTOR)).filter(
                element =>
                    // `:disabled` also covers controls disabled by an ancestor fieldset,
                    // which the attribute selectors above cannot see.
                    !element.matches(':disabled') &&
                    window.getComputedStyle(element).visibility !== 'hidden' &&
                    isDisplayed(element) &&
                    !element.closest('[inert], [aria-hidden="true"], [hidden]')
            );

        // Falls back to the container, which needs tabIndex={-1} to take focus.
        (getFocusableElements()[0] ?? container).focus();

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

        // Containment is not enough: an attribute change can leave the focused control
        // in the DOM but no longer eligible, so re-check eligibility, not just presence.
        const handleMutation = () => {
            if (!isTopTrap()) return;
            const focusableElements = getFocusableElements();
            const activeElement = document.activeElement;
            const eligible =
                activeElement === container || focusableElements.includes(activeElement);

            if (!eligible) {
                (focusableElements[0] ?? container).focus();
            }
        };

        // Set up MutationObserver for dynamic content
        observerRef.current = new MutationObserver(handleMutation);
        // No attributeFilter: eligibility now also depends on style, hidden, inert and
        // aria-hidden, and any filter here silently drifts out of sync with it.
        observerRef.current.observe(container, {
            childList: true,
            subtree: true,
            attributes: true,
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
