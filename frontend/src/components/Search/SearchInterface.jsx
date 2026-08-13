import React, { useState, useCallback, useRef, useEffect } from 'react';
import PropTypes from 'prop-types';
import { useLocation } from 'react-router';
import { useSearchCoordinator } from '../../contexts/SearchCoordinatorContext.jsx';

/**
 * SearchInterface — controlled by SearchCoordinatorContext.
 *
 * Input value reads from `coordinator.getSearchState(searchPageType).term`.
 * Typing dispatches to `coordinator.search(type, value)` which updates the
 * term synchronously and debounces the registered handler (300ms). Any seed
 * from outside the bar — URL ?q=, programmatic, another component — flows
 * back into the input because the input is controlled by coordinator state.
 *
 * @param {Object} props
 * @param {string} props.searchPageType — 'media' | 'posters' etc.
 * @param {string} [props.searchSubtype] — e.g. 'assets'
 * @param {string} [props.placeholder]
 * @param {Array} [props.suggestions] — recent-searches list
 * @param {Function} [props.onSuggestionSelect] — optional override for chip clicks
 */
const SearchInterface = React.memo(
    ({
        searchPageType,
        searchSubtype,
        placeholder = 'Search media...',
        suggestions = [],
        onSuggestionSelect,
    }) => {
        const { getSearchState, search, clearSearch } = useSearchCoordinator();
        const term = getSearchState(searchPageType).term || '';

        const [isActive, setIsActive] = useState(false);
        const [showSuggestions, setShowSuggestions] = useState(false);
        const inputRef = useRef(null);
        const suggestionsRef = useRef(null);

        // Sync the coordinator term to the URL `?q=` whenever they differ.
        // Runs on searchPageType change AND on URL search-string change so
        // same-route navigation (e.g. clicking an unmatched-title link on the
        // poster stats page while already on /poster/search/assets) reseeds
        // the bar instead of leaving the old term sticky. A URL with no `?q=`
        // is treated as an explicit reset and clears the bar.
        //
        // Typing in the bar doesn't push to the URL, so location.search stays
        // stable during input and this effect doesn't fight the user.
        const location = useLocation();
        useEffect(() => {
            const q = new URLSearchParams(location.search).get('q') || '';
            const current = getSearchState(searchPageType).term || '';
            if (q !== current) {
                if (q) {
                    search(searchPageType, q);
                } else {
                    clearSearch(searchPageType);
                }
            }
            // eslint-disable-next-line react-hooks/exhaustive-deps
        }, [searchPageType, location.search]);

        const handleSearchChange = useCallback(
            event => {
                search(searchPageType, event.target.value);
            },
            [search, searchPageType]
        );

        const handleFocus = useCallback(() => {
            setIsActive(true);
            if (suggestions.length > 0 && !term) {
                setShowSuggestions(true);
            }
        }, [suggestions.length, term]);

        const handleBlur = useCallback(e => {
            if (suggestionsRef.current?.contains(e.relatedTarget)) return;
            setIsActive(false);
            setTimeout(() => setShowSuggestions(false), 150);
        }, []);

        const handleClear = useCallback(() => {
            clearSearch(searchPageType);
            inputRef.current?.focus();
        }, [clearSearch, searchPageType]);

        const handleSubmit = useCallback(
            event => {
                event.preventDefault();
                if (term.trim()) {
                    search(searchPageType, term.trim(), { immediate: true });
                }
            },
            [search, searchPageType, term]
        );

        const getContextualPlaceholder = () => {
            if (searchPageType === 'media') {
                return 'Search media...';
            }
            if (searchPageType === 'posters') {
                if (searchSubtype === 'assets') {
                    return 'Search poster assets...';
                }
            }
            return placeholder;
        };

        return (
            <div className="w-full relative" role="search">
                <form className="w-full" onSubmit={handleSubmit}>
                    <div
                        className={`relative ${isActive ? 'active' : ''} ${term ? 'has-value' : ''}`}
                    >
                        <div className="relative flex items-center bg-surface border rounded-lg h-input focus-within:border-primary">
                            <span
                                className="absolute left-3 text-fg-muted text-lg pointer-events-none z-10 material-symbols-outlined"
                                aria-hidden="true"
                            >
                                search
                            </span>
                            <input
                                ref={inputRef}
                                type="text"
                                className="flex-1 min-w-0 py-2 pr-11 pl-10 border-none bg-transparent text-fg outline-none w-full h-full"
                                placeholder={getContextualPlaceholder()}
                                value={term}
                                onChange={handleSearchChange}
                                onFocus={handleFocus}
                                onBlur={handleBlur}
                                aria-label={`Search ${searchPageType === 'media' ? 'media' : 'posters'}`}
                            />
                            {term && (
                                <button
                                    type="button"
                                    className="absolute right-0 top-1/2 -translate-y-1/2 touch-target flex items-center justify-center border-none text-fg-muted cursor-pointer transition-colors bg-transparent hover:text-fg"
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

                {showSuggestions && suggestions.length > 0 && (
                    <div
                        ref={suggestionsRef}
                        className="absolute z-20 w-full mt-1 bg-surface border border-border-light rounded-lg max-h-48 overflow-y-auto"
                        role="listbox"
                        aria-label="Search suggestions"
                    >
                        <div className="px-3 py-1.5 text-xs text-fg-muted border-b border-border">
                            Recent searches
                        </div>
                        {suggestions.map((suggestion, idx) => (
                            <button
                                key={suggestion.id || idx}
                                type="button"
                                role="option"
                                className="w-full text-left px-3 py-2 text-sm text-fg hover:bg-surface-hover cursor-pointer border-none bg-transparent flex items-center gap-2"
                                onMouseDown={e => {
                                    e.preventDefault();
                                    const value = suggestion.term || suggestion;
                                    setShowSuggestions(false);
                                    if (onSuggestionSelect) {
                                        onSuggestionSelect(value);
                                    } else {
                                        search(searchPageType, value, { immediate: true });
                                    }
                                }}
                            >
                                <span
                                    className="material-symbols-outlined text-fg-muted text-base"
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
    placeholder: PropTypes.string,
    suggestions: PropTypes.array,
    onSuggestionSelect: PropTypes.func,
};

export default SearchInterface;
