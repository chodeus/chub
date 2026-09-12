import React, { useRef, useEffect } from 'react';
import PropTypes from 'prop-types';
import { ToolBarProvider } from './ToolBarContext';
import ToolBarSection from './Section';
import ToolBarButton from './Button';
import ToolBarSeparator from './Separator';
import ToolBarOverflow from './Overflow';

const EDITABLE_SELECTOR =
    'input, textarea, select, [contenteditable]:not([contenteditable="false"])';

/** Compound toolbar: provides ToolBar context and Arrow/Home/End focus movement between buttons. */
const ToolBar = ({
    children,
    mobileBreakpoint = 768,
    className = 'flex justify-between flex-none px-2 md:px-4 bg-surface text-fg border-b border-border',
}) => {
    const toolbarRef = useRef(null);

    // Keyboard navigation
    useEffect(() => {
        const handleKeyDown = event => {
            if (!toolbarRef.current || event.target.closest(EDITABLE_SELECTOR)) return;

            const buttons = Array.from(
                toolbarRef.current.querySelectorAll('button:not([disabled])')
            );
            if (buttons.length === 0) return;

            const currentIndex = buttons.indexOf(document.activeElement);

            switch (event.key) {
                case 'ArrowLeft':
                    event.preventDefault();
                    if (currentIndex > 0) {
                        buttons[currentIndex - 1].focus();
                    } else {
                        buttons[buttons.length - 1].focus(); // Wrap to end
                    }
                    break;

                case 'ArrowRight':
                    event.preventDefault();
                    if (currentIndex < buttons.length - 1) {
                        buttons[currentIndex + 1].focus();
                    } else {
                        buttons[0].focus(); // Wrap to start
                    }
                    break;

                case 'Home':
                    event.preventDefault();
                    buttons[0].focus();
                    break;

                case 'End':
                    event.preventDefault();
                    buttons[buttons.length - 1].focus();
                    break;

                default:
                    break;
            }
        };

        const toolbar = toolbarRef.current;
        if (toolbar) {
            toolbar.addEventListener('keydown', handleKeyDown);
            return () => toolbar.removeEventListener('keydown', handleKeyDown);
        }
    }, []);

    return (
        <ToolBarProvider mobileBreakpoint={mobileBreakpoint}>
            <div ref={toolbarRef} className={className} role="toolbar" aria-label="Toolbar">
                {children}
            </div>
        </ToolBarProvider>
    );
};

ToolBar.displayName = 'ToolBar';

ToolBar.propTypes = {
    children: PropTypes.node.isRequired,
    mobileBreakpoint: PropTypes.number,
    className: PropTypes.string,
};

// Attach subcomponents for compound pattern
ToolBar.Section = ToolBarSection;
ToolBar.Button = ToolBarButton;
ToolBar.Separator = ToolBarSeparator;
ToolBar.Overflow = ToolBarOverflow;

export default ToolBar;
