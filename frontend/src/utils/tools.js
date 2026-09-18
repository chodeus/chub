/** snake_case to Title Case for display; '' for any non-string. */
export function humanize(key) {
    if (typeof key !== 'string') return '';
    return key
        .replace(/_/g, ' ') // Replace underscores with spaces
        .replace(/\b\w/g, char => char.toUpperCase()); // Capitalize first letter of each word
}
