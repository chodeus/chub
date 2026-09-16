/** TagInput - string-array editor with array suggestions and the ARIA combobox pattern. */

import React, { useState, useRef, useCallback, useMemo, useId, useEffect } from 'react';
import { Badge } from './Badge';

/**
 * TagInput component for managing collections of strings with autocomplete
 *
 * @param {Object} props - Component props
 * @param {string[]} props.items - Current array of string items
 * @param {Function} props.onItemsChange - Callback when items array changes
 * @param {string[]} props.suggestions - Autocomplete suggestions
 * @param {boolean} props.allowCustom - Allow typing arbitrary strings
 * @param {string} props.placeholder - Input placeholder text
 * @param {boolean} props.disabled - Disabled state
 * @param {number} props.maxItems - Maximum number of items allowed
 * @param {Function} props.filterFunction - Custom filter for suggestions
 * @param {Function} props.validateItem - Custom validation for new items
 * @param {boolean} props.caseSensitive - Case sensitive duplicate detection
 * @param {string} props.addLabel - Accessible label for add action
 * @param {string} props.removeLabel - Accessible label for remove action
 * @param {Object} props.badgeProps - Props to pass to Badge components
 * @param {string} props.className - Additional CSS classes
 */
export const TagInput = React.memo(
    ({
        items = [],
        onItemsChange,
        suggestions = [],
        allowCustom = true,
        placeholder = 'Add item...',
        disabled = false,
        maxItems,
        filterFunction,
        validateItem,
        caseSensitive = false,
        addLabel = 'Add item',
        removeLabel = 'Remove item',
        badgeProps = {},
        className = '',
        id,
        name,
        'aria-describedby': ariaDescribedby,
        'aria-invalid': ariaInvalid,
        'aria-labelledby': ariaLabelledby,
        ...restProps
    }) => {
        // State management for interaction patterns
        const [inputValue, setInputValue] = useState('');
        const [showSuggestions, setShowSuggestions] = useState(false);
        const [focusedSuggestionIndex, setFocusedSuggestionIndex] = useState(-1);
        const uid = useId();
        const listboxId = `${uid}-suggestions`;
        const descriptionId = `${uid}-description`;

        // Refs for DOM interaction and focus management
        const inputRef = useRef(null);
        const containerRef = useRef(null);
        const blurTimerRef = useRef(null);

        useEffect(() => () => clearTimeout(blurTimerRef.current), []);

        // Generate suggestions based on input value
        const filteredSuggestions = useMemo(() => {
            if (!inputValue.trim() && !showSuggestions) return [];

            const suggestionArray = Array.isArray(suggestions) ? suggestions : [];
            // Dedupe here, not at render: the keyboard index addresses this same array.
            const unique = [...new Set(suggestionArray)];

            if (!inputValue.trim()) return unique;

            // Suggestion filtering logic
            const filterFn =
                filterFunction ||
                ((suggestion, input) => {
                    const suggestionText = caseSensitive ? suggestion : suggestion.toLowerCase();
                    const inputText = caseSensitive ? input : input.toLowerCase();
                    return suggestionText.includes(inputText);
                });

            return unique
                .filter(suggestion => filterFn(suggestion, inputValue))
                .filter(suggestion => {
                    // Exclude already selected items
                    const compareItems = caseSensitive
                        ? items
                        : items.map(item => item.toLowerCase());
                    const compareSuggestion = caseSensitive ? suggestion : suggestion.toLowerCase();
                    return !compareItems.includes(compareSuggestion);
                });
        }, [inputValue, suggestions, items, filterFunction, caseSensitive, showSuggestions]);

        // Item management with duplicate prevention
        const addItem = useCallback(
            newItem => {
                if (!newItem || !newItem.trim()) return false;

                const trimmedItem = newItem.trim();

                // Validate item if validation function provided
                if (validateItem && !validateItem(trimmedItem)) {
                    return false;
                }

                // Check for duplicates (case-sensitive or not)
                const compareItems = caseSensitive ? items : items.map(item => item.toLowerCase());
                const compareNew = caseSensitive ? trimmedItem : trimmedItem.toLowerCase();

                if (compareItems.includes(compareNew)) {
                    return false; // Duplicate found
                }

                // Check max items limit
                if (maxItems && items.length >= maxItems) {
                    return false; // Max items reached
                }

                // Add the item
                const newItems = [...items, trimmedItem];
                onItemsChange?.(newItems);
                return true;
            },
            [items, onItemsChange, caseSensitive, maxItems, validateItem]
        );

        const removeItem = useCallback(
            indexToRemove => {
                const newItems = items.filter((_, index) => index !== indexToRemove);
                onItemsChange?.(newItems);
            },
            [items, onItemsChange]
        );

        // Input handling with suggestion management
        const handleInputChange = e => {
            const value = e.target.value;
            setInputValue(value);
            setFocusedSuggestionIndex(-1);
            setShowSuggestions(value.length > 0 || suggestions.length > 0);
        };

        const handleInputSubmit = () => {
            if (!inputValue.trim()) return;

            // If a suggestion is focused, use it
            if (focusedSuggestionIndex >= 0 && filteredSuggestions[focusedSuggestionIndex]) {
                const suggestionToAdd = filteredSuggestions[focusedSuggestionIndex];
                if (addItem(suggestionToAdd)) {
                    setInputValue('');
                    setShowSuggestions(false);
                    setFocusedSuggestionIndex(-1);
                }
                return;
            }

            // Otherwise, add custom input (if allowed)
            if (allowCustom) {
                if (addItem(inputValue)) {
                    setInputValue('');
                    setShowSuggestions(false);
                    setFocusedSuggestionIndex(-1);
                }
            }
        };

        // Comprehensive keyboard navigation
        const handleKeyDown = e => {
            if (disabled) return;

            switch (e.key) {
                case 'ArrowDown':
                    e.preventDefault();
                    if (showSuggestions && filteredSuggestions.length > 0) {
                        setFocusedSuggestionIndex(prev =>
                            prev < filteredSuggestions.length - 1 ? prev + 1 : 0
                        );
                    }
                    break;

                case 'ArrowUp':
                    e.preventDefault();
                    if (showSuggestions && filteredSuggestions.length > 0) {
                        setFocusedSuggestionIndex(prev =>
                            prev > 0 ? prev - 1 : filteredSuggestions.length - 1
                        );
                    }
                    break;

                case 'Enter':
                    e.preventDefault();
                    handleInputSubmit();
                    break;

                case 'Escape':
                    setShowSuggestions(false);
                    setFocusedSuggestionIndex(-1);
                    if (!inputValue) {
                        inputRef.current?.blur();
                    }
                    break;

                case 'Tab':
                    // Allow normal tab behavior but close suggestions
                    setShowSuggestions(false);
                    setFocusedSuggestionIndex(-1);
                    break;

                case ',':
                    // Comma as separator (common UX pattern)
                    e.preventDefault();
                    handleInputSubmit();
                    break;

                default:
                    break;
            }
        };

        // Suggestion selection handlers
        const handleSuggestionClick = suggestion => {
            if (addItem(suggestion)) {
                setInputValue('');
                setShowSuggestions(false);
                setFocusedSuggestionIndex(-1);
                inputRef.current?.focus();
            }
        };

        // Focus management for accessibility
        const handleInputFocus = () => {
            if (suggestions.length > 0 || inputValue) {
                setShowSuggestions(true);
            }
        };

        const handleInputBlur = () => {
            // Delay hiding suggestions to allow suggestion clicks
            clearTimeout(blurTimerRef.current);
            blurTimerRef.current = setTimeout(() => {
                if (!containerRef.current?.contains(document.activeElement)) {
                    setShowSuggestions(false);
                    setFocusedSuggestionIndex(-1);
                }
            }, 200);
        };

        // Badge removal with keyboard support
        const handleBadgeRemove = useCallback(
            indexToRemove => {
                removeItem(indexToRemove);
                // Return focus to input for continued interaction
                inputRef.current?.focus();
            },
            [removeItem]
        );

        // Container classes for responsive layout
        const containerClasses = ['relative', 'w-full', className].filter(Boolean).join(' ');

        // Suggestions dropdown styling with proper theming
        const suggestionsClasses = [
            'absolute',
            'top-full',
            'left-0',
            'right-0',
            'z-50',
            'bg-surface',
            'border',
            'border-border',
            'rounded-lg',
            'shadow-lg',
            'max-h-48',
            'overflow-y-auto',
            'mt-1',
        ]
            .filter(Boolean)
            .join(' ');

        return (
            <div ref={containerRef} className={containerClasses} {...restProps}>
                {/* Input container with badges inside */}
                <div className="relative">
                    {/* Custom input container with badges inside */}
                    <div
                        className={[
                            'min-h-11 border border-border rounded-lg bg-surface',
                            'flex flex-wrap gap-1 p-2',
                            'focus-within:border-primary focus-within:ring-1 focus-within:ring-primary',
                            disabled && 'opacity-50 bg-input-disabled cursor-not-allowed',
                        ]
                            .filter(Boolean)
                            .join(' ')}
                    >
                        {/* Badge display inside input container */}
                        {items.length > 0 && (
                            <div
                                className="flex flex-wrap gap-1"
                                role="list"
                                aria-label="Selected items"
                            >
                                {items.map((item, index) => (
                                    <div key={`${item}-${index}`} role="listitem">
                                        <Badge
                                            onRemove={
                                                disabled
                                                    ? undefined
                                                    : () => handleBadgeRemove(index)
                                            }
                                            removeLabel={removeLabel}
                                            variant="interactive"
                                            size="small"
                                            {...badgeProps}
                                        >
                                            {item}
                                        </Badge>
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* Invisible input that takes remaining space */}
                        <input
                            ref={inputRef}
                            id={id}
                            name={name}
                            value={inputValue}
                            onChange={handleInputChange}
                            onKeyDown={handleKeyDown}
                            onFocus={handleInputFocus}
                            onBlur={handleInputBlur}
                            placeholder={items.length === 0 ? placeholder : ''}
                            disabled={disabled}
                            className={[
                                'flex-1 min-w-0 bg-transparent border-none outline-none',
                                'text-fg placeholder:text-fg-subtle',
                                'min-h-7', // Slightly smaller than container
                            ]
                                .filter(Boolean)
                                .join(' ')}
                            role="combobox"
                            aria-expanded={showSuggestions}
                            aria-haspopup="listbox"
                            aria-autocomplete="both"
                            aria-controls={showSuggestions ? listboxId : undefined}
                            aria-activedescendant={
                                showSuggestions &&
                                filteredSuggestions[focusedSuggestionIndex] !== undefined
                                    ? `${listboxId}-option-${focusedSuggestionIndex}`
                                    : undefined
                            }
                            aria-describedby={[descriptionId, ariaDescribedby]
                                .filter(Boolean)
                                .join(' ')}
                            aria-invalid={ariaInvalid}
                            aria-labelledby={ariaLabelledby}
                            aria-label={`${addLabel}. ${items.length} items selected.`}
                            autoComplete="off"
                        />
                    </div>

                    {/* Hidden description for screen readers */}
                    <div id={descriptionId} className="sr-only">
                        {allowCustom
                            ? 'Type to add new items or select from suggestions. Use commas or Enter to add items.'
                            : 'Select from available suggestions.'}
                        {maxItems && ` Maximum ${maxItems} items allowed.`}
                        {items.length > 0 && ` Currently ${items.length} items selected.`}
                    </div>

                    {/* Suggestions dropdown with ARIA listbox pattern */}
                    {showSuggestions && (
                        <div
                            className={suggestionsClasses}
                            role="listbox"
                            id={listboxId}
                            aria-label="Available suggestions"
                        >
                            {filteredSuggestions.length === 0 && inputValue && (
                                <div className="px-3 py-2 text-sm text-fg-muted" role="status">
                                    {allowCustom
                                        ? `Press Enter to add "${inputValue}"`
                                        : 'No matching suggestions'}
                                </div>
                            )}

                            {filteredSuggestions.map((suggestion, index) => (
                                <div
                                    key={suggestion}
                                    id={`${listboxId}-option-${index}`}
                                    role="option"
                                    aria-selected={index === focusedSuggestionIndex}
                                    className={[
                                        'touch-target flex items-center px-3 py-2 cursor-pointer text-sm',
                                        index === focusedSuggestionIndex
                                            ? 'bg-primary text-on-color'
                                            : 'hover:bg-surface-hover text-fg',
                                    ]
                                        .filter(Boolean)
                                        .join(' ')}
                                    onClick={() => handleSuggestionClick(suggestion)}
                                >
                                    {suggestion}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        );
    }
);

TagInput.displayName = 'TagInput';

export default TagInput;
