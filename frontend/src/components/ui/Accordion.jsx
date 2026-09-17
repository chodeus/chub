/** Spacing container for AccordionItem children. */
export const Accordion = ({ children, className = '' }) => (
    <div className={`space-y-3 ${className}`}>{children}</div>
);

Accordion.displayName = 'Accordion';

export default Accordion;
