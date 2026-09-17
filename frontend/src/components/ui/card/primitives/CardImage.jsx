import React, { useState, useCallback } from 'react';
import PropTypes from 'prop-types';

/** Card image in an aspect-ratio box, with loading and error states. */
export const CardImage = React.memo(
    ({ src, alt, aspectRatio = '16/9', objectFit = 'cover', className = '' }) => {
        const [isLoading, setIsLoading] = useState(true);
        const [hasError, setHasError] = useState(false);
        const [prevSrc, setPrevSrc] = useState(src);

        // Adjust state during render rather than in an effect (see EditMediaModal):
        // without this, one failed image leaves the fallback showing for every later src.
        if (src !== prevSrc) {
            setPrevSrc(src);
            setIsLoading(true);
            setHasError(false);
        }

        const handleLoad = useCallback(() => {
            setIsLoading(false);
        }, []);

        const handleError = useCallback(() => {
            setIsLoading(false);
            setHasError(true);
        }, []);

        // Map aspect ratio to utility class (sizing.css)
        const aspectRatioMap = {
            '16/9': 'aspect-video', // Built-in CSS aspect-ratio
            '4/3': 'aspect-4/3',
            '1/1': 'aspect-square',
            '3/2': 'aspect-3/2',
        };

        // Map object-fit to utility class (images.css)
        const objectFitMap = {
            cover: 'object-cover',
            contain: 'object-contain',
            fill: 'object-fill',
            none: 'object-none',
        };

        const containerClasses = [
            'relative w-full overflow-hidden bg-surface-alt',
            aspectRatioMap[aspectRatio],
            isLoading && 'img-loading',
            className,
        ]
            .filter(Boolean)
            .join(' ');

        const imgClasses = ['w-full h-full block', objectFitMap[objectFit]].join(' ');

        return (
            <div className={containerClasses}>
                {!hasError ? (
                    <img
                        src={src}
                        alt={alt}
                        onLoad={handleLoad}
                        onError={handleError}
                        className={imgClasses}
                    />
                ) : (
                    <div className="flex flex-col items-center justify-center h-full gap-2 text-fg-muted text-sm">
                        <span className="material-symbols-outlined text-2xl">broken_image</span>
                        <span>Failed to load image</span>
                    </div>
                )}
            </div>
        );
    }
);

CardImage.displayName = 'CardImage';

CardImage.propTypes = {
    src: PropTypes.string.isRequired,
    alt: PropTypes.string.isRequired,
    aspectRatio: PropTypes.oneOf(['16/9', '4/3', '1/1', '3/2']),
    objectFit: PropTypes.oneOf(['cover', 'contain', 'fill', 'none']),
    className: PropTypes.string,
};
