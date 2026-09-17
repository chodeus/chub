import { useState, useContext, createContext } from 'react';

/** Shares { isExpanded, handleToggle } with the Header and Body subcomponents. */
const AccordionItemContext = createContext(null);

/** Accordion row: uncontrolled via `defaultExpanded`, or controlled by passing
 *  `isExpanded` together with `onToggle`. */
export const AccordionItem = ({
    children,
    defaultExpanded = false,
    isExpanded: controlledExpanded,
    onToggle,
    className = '',
}) => {
    // State management: controlled vs uncontrolled
    const [internalExpanded, setInternalExpanded] = useState(defaultExpanded);
    const isControlled = controlledExpanded !== undefined;
    const isExpanded = isControlled ? controlledExpanded : internalExpanded;

    const handleToggle = () => {
        const newExpanded = !isExpanded;

        if (!isControlled) {
            setInternalExpanded(newExpanded);
        }

        onToggle?.(newExpanded);
    };

    return (
        <AccordionItemContext.Provider value={{ isExpanded, handleToggle }}>
            <details
                className={`accordion-item border border-border-subtle rounded-lg overflow-hidden ${className}`}
                open={isExpanded}
            >
                {children}
            </details>
        </AccordionItemContext.Provider>
    );
};

/** Header row; `children` may be a render prop receiving { isExpanded }. */
const AccordionHeader = ({ children, className = '' }) => {
    const context = useContext(AccordionItemContext);

    if (!context) {
        throw new Error('AccordionItem.Header must be used within AccordionItem');
    }

    const { isExpanded, handleToggle } = context;

    const handleClick = event => {
        event.preventDefault(); // Prevent native details toggle
        handleToggle();
    };

    const content = typeof children === 'function' ? children({ isExpanded }) : children;

    return (
        <summary
            className={`accordion-header ${className}`}
            onClick={handleClick}
            role="button"
            tabIndex={0}
            aria-expanded={isExpanded}
            onKeyDown={e => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleToggle();
                }
            }}
        >
            {content}
        </summary>
    );
};

AccordionHeader.displayName = 'AccordionItem.Header';
AccordionItem.Header = AccordionHeader;

/** Body content; aria-hidden while the item is collapsed. */
const AccordionBody = ({ children, className = '' }) => {
    const context = useContext(AccordionItemContext);

    if (!context) {
        throw new Error('AccordionItem.Body must be used within AccordionItem');
    }

    const { isExpanded } = context;

    return (
        <div className={className} aria-hidden={!isExpanded}>
            {children}
        </div>
    );
};

AccordionBody.displayName = 'AccordionItem.Body';
AccordionItem.Body = AccordionBody;

AccordionItem.displayName = 'AccordionItem';

export default AccordionItem;
