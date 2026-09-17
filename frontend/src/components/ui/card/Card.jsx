import React from 'react';
import PropTypes from 'prop-types';
import { CardContainer, CardHeader, CardBody, CardFooter, CardImage } from './primitives';

/** Compound card: Card.Image, Card.Header, Card.Body, Card.Footer. */
export const Card = React.memo(
    ({
        children,
        hoverable = false,
        clickable = false,
        onClick,
        selected = false,
        className = '',
        ...htmlProps
    }) => {
        return (
            <CardContainer
                hoverable={hoverable}
                clickable={clickable}
                onClick={onClick}
                selected={selected}
                className={className}
                {...htmlProps}
            >
                {children}
            </CardContainer>
        );
    }
);

// Attach subcomponents for compound component pattern
Card.Image = CardImage;
Card.Header = CardHeader;
Card.Body = CardBody;
Card.Footer = CardFooter;

Card.displayName = 'Card';

Card.propTypes = {
    children: PropTypes.node.isRequired,
    hoverable: PropTypes.bool,
    clickable: PropTypes.bool,
    onClick: PropTypes.func,
    selected: PropTypes.bool,
    className: PropTypes.string,
};
