import React, { useState, useCallback, useRef } from 'react';
import PropTypes from 'prop-types';
import { useDebounce } from '../../hooks/useDebounce.js';

/**
 * SearchInterface Component for CHUB application
 *
 * Professional search interface providing context-aware search functionality
 * with debounced input, responsive design, and accessibility compliance.
 *
 * Features:
 * - Debounced search input (300ms delay) for performance optimization
 * - Context-aware placeholder text based on search page type
 * - Responsive design with mobile-first approach (375px+)
 * - Touch-optimized interaction targets (44px minimum)
 * - Real-time search state feedback and visual indicators
 * - WCAG 2.1 AA compliant with proper ARIA labels
 * - Clear search functionality with keyboard accessibility
 * - Form submission handling for Enter key support
 *
 * @param {Object} props - Component props
 * @param {string} props.searchPageType - Type of search page ('media', 'posters')
 * @param {string} [props.searchSubtype] - Search subtype ('assets', 'gdrive') or null for basic search
 * @param {Function} props.onSearch - Callback function for search events, receives search term as parameter
 * @param {string} [props.placeholder] - Custom placeholder text, falls back to contextual placeholder
 */
const SearchInterface = React.memo(
    ({
        searchPageType,
        searchSubtype,
        onSearch,
        placeholder = 'Search media...',
        suggestions = [],
        onSuggestionSelect,
    }) => {
        const [searchTerm, setSearchTerm] = useState('');
        const [isActive, setIsActive] = useState(false);
        const [showSuggestions, setShowSuggestions] = useState(false);
        const inputRef = useRef(null);
        const suggestionsRef = useRef(null);

        // Debounced search with 300ms delay
        const debouncedSearchTerm = useDebounce(searchTerm, 300);

        /**
         * Handle search input change
         */
        const handleSearchChange = useCallback(event => {
            const value = event.target.value;
            setSearchTerm(value);
        }, []);

        /**
         * Handle search input focus
         */
        const handleFocus = useCallback(() => {
            setIsActive(true);
            if (suggestions.length > 0 && !searchTerm) {
                setShowSuggestions(true);
            }
        }, [suggestions.length, searchTerm]);

        /**
         * Handle search input blur
         */
        const handleBlur = useCallback(e => {
            // Delay hiding so click on suggestion can register
            if (suggestionsRef.current?.contains(e.relatedTarget)) return;
            setIsActive(false);
            setTimeout(() => setShowSuggestions(false), 150);
        }, []);

        /**
         * Handle clear search
         */
        const handleClear = useCallback(() => {
            setSearchTerm('');
            inputRef.current?.focus();
        }, []);

        /**
         * Handle form submission
         */
        const handleSubmit = useCallback(
            event => {
                event.preventDefault();
                if (onSearch && searchTerm.trim()) {
                    onSearch(searchTerm.trim());
                }
            },
            [onSearch, searchTerm]
        );

        // Execute search when debounced term changes
        React.useEffect(() => {
            if (onSearch && debouncedSearchTerm !== null) {
                onSearch(debouncedSearchTerm);
            }
        }, [debouncedSearchTerm, onSearch]);

        /**
         * Get appropriate placeholder text based on search context
         */
        const getContextualPlaceholder = () => {
            if (searchPageType === 'media') {
                return 'Search media...';
            }
            if (searchPageType === 'posters') {
                if (searchSubtype === 'assets') {
                    return 'Search poster assets...';
                }
                if (searchSubtype === 'gdrive') {
                    return 'Search Google Drive...';
                }
            }
            return placeholder;
        };

        return (
            <div className="w-full relative" role="search">
                {/* Tier 1: Search Field */}
                <form className="w-full" onSubmit={handleSubmit}>
                    <div
                        className={`relative ${isActive ? 'active' : ''} ${searchTerm ? 'has-value' : ''}`}
                    >
                        <div className="relative flex items-center bg-surface border rounded-lg h-input focus-within:border-primary">
                            <span
                                className="absolute left-3 text-secondary text-lg pointer-events-none z-10 material-symbols-outlined"
                                aria-hidden="true"
                            >
                                search
                            </span>
                            <input
                                ref={inputRef}
                                type="text"
                                className="flex-1 py-input pr-4 pl-10 border-none bg-transparent text-primary outline-none w-full h-full"
                                placeholder={getContextualPlaceholder()}
                                value={searchTerm}
                                onChange={handleSearchChange}
                                onFocus={handleFocus}
                                onBlur={handleBlur}
                                aria-label={`Search ${searchPageType === 'media' ? 'media' : 'posters'}`}
                            />
                            {searchTerm && (
                                <button
                                    type="button"
                                    className="absolute right-2 top-1/2 -translate-y-1/2 w-8 h-8 flex items-center justify-center border-none text-secondary cursor-pointer transition-colors bg-transparent hover:text-primary"
                                    onClick={handleClear}
                                    aria-label="Clear search"
                                    tabIndex={0}
                                >
                                    <span className="material-symbols-outlined" aria-hidden="true">
                                        close
                                    </span>
                                </button>
                            )}
                        </div>
                    </div>
                </form>

                {/* Search suggestions dropdown */}
                {showSuggestions && suggestions.length > 0 && (
                    <div
                        ref={suggestionsRef}
                        className="absolute z-20 w-full mt-1 bg-surface border border-border-light rounded-lg max-h-48 overflow-y-auto"
                        role="listbox"
                        aria-label="Search suggestions"
                    >
                        <div className="px-3 py-1.5 text-xs text-secondary border-b border-border">
                            Recent searches
                        </div>
                        {suggestions.map((suggestion, idx) => (
                            <button
                                key={suggestion.id || idx}
                                type="button"
                                role="option"
                                className="w-full text-left px-3 py-2 text-sm text-primary hover:bg-hover cursor-pointer border-none bg-transparent flex items-center gap-2"
                                onMouseDown={e => {
                                    e.preventDefault();
                                    const term = suggestion.term || suggestion;
                                    setSearchTerm(term);
                                    setShowSuggestions(false);
                                    if (onSuggestionSelect) onSuggestionSelect(term);
                                    else if (onSearch) onSearch(term);
                                }}
                            >
                                <span
                                    className="material-symbols-outlined text-secondary text-base"
                                    aria-hidden="true"
                                >
                                    history
                                </span>
                                {suggestion.term || suggestion}
                            </button>
                        ))}
                    </div>
                )}
            </div>
        );
    }
);

SearchInterface.displayName = 'SearchInterface';

SearchInterface.propTypes = {
    searchPageType: PropTypes.string.isRequired,
    searchSubtype: PropTypes.string,
    onSearch: PropTypes.func.isRequired,
    placeholder: PropTypes.string,
    suggestions: PropTypes.array,
    onSuggestionSelect: PropTypes.func,
};

export default SearchInterface;
