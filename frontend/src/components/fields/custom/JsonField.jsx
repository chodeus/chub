import { useId, useCallback, useMemo, useState } from 'react';
import { FieldWrapper } from '../primitives/FieldWrapper';
import { FieldLabel } from '../primitives/FieldLabel';
import { FieldDescription } from '../primitives/FieldDescription';
import { FieldError } from '../primitives/FieldError';
import { TextareaBase } from '../primitives/TextareaBase';

// No rest/spread here: renderField hands every field component non-DOM
// context (moduleConfig, rootConfig, ...), which must not reach the textarea.
export const JsonField = ({
    field,
    value,
    onChange,
    disabled = false,
    highlightInvalid = false,
    errorMessage,
}) => {
    const inputId = useId();

    // Convert value to string representation
    const getStringValue = useCallback(() => {
        if (typeof value === 'string') {
            return value;
        } else if (typeof value === 'object' && value !== null) {
            try {
                return JSON.stringify(value, null, 2);
            } catch {
                return String(value);
            }
        }
        return value || '';
    }, [value]);

    const [textValue, setTextValue] = useState(() => getStringValue());

    // Sync textValue when the prop `value` changes (external update). Uses the
    // "adjusting state while rendering" pattern (React docs) rather than a
    // setState-in-effect.
    const [prevPropValue, setPrevPropValue] = useState(value);
    if (prevPropValue !== value) {
        setPrevPropValue(value);
        setTextValue(getStringValue());
    }

    const jsonError = useMemo(() => {
        if (!textValue.trim()) return null;
        try {
            JSON.parse(textValue);
            return null;
        } catch (error) {
            return `Invalid JSON: ${error.message}`;
        }
    }, [textValue]);

    // Invalid text still reaches the form so the user can keep typing.
    const handleChange = useCallback(
        e => {
            const newTextValue = e.target.value;
            setTextValue(newTextValue);
            onChange(newTextValue.trim() ? newTextValue : '');
        },
        [onChange]
    );

    // Format JSON
    const formatJson = useCallback(() => {
        if (jsonError) return;
        const formatted = JSON.stringify(JSON.parse(textValue), null, 2);
        setTextValue(formatted);
        onChange(formatted);
    }, [jsonError, textValue, onChange]);

    // Minify JSON
    const minifyJson = useCallback(() => {
        if (jsonError) return;
        const minified = JSON.stringify(JSON.parse(textValue));
        setTextValue(minified);
        onChange(minified);
    }, [jsonError, textValue, onChange]);

    const hasError = Boolean(errorMessage || jsonError);
    const errorToShow = errorMessage || jsonError;
    const minRows = field.minRows ?? 8;
    const maxRows = field.maxRows ?? 20;

    // Calculate dynamic rows based on content
    const rows = Math.max(minRows, Math.min(maxRows, (textValue.match(/\n/g) || []).length + 3));

    return (
        <FieldWrapper invalid={highlightInvalid || hasError}>
            <div>
                <FieldLabel htmlFor={inputId} label={field.label} required={field.required} />

                <div>
                    <button
                        type="button"
                        onClick={formatJson}
                        disabled={disabled || !textValue.trim()}
                        className="touch-target bg-surface text-fg px-3 py-2 border border-border rounded-lg cursor-pointer transition-colors hover:bg-surface-hover inline-flex items-center justify-center text-sm"
                        title="Format JSON with indentation"
                        aria-label="Format JSON"
                    >
                        Format
                    </button>
                    <button
                        type="button"
                        onClick={minifyJson}
                        disabled={disabled || !textValue.trim()}
                        className="touch-target bg-surface text-fg px-3 py-2 border border-border rounded-lg cursor-pointer transition-colors hover:bg-surface-hover inline-flex items-center justify-center text-sm"
                        title="Minify JSON to single line"
                        aria-label="Minify JSON"
                    >
                        Minify
                    </button>
                </div>
            </div>

            <div>
                <TextareaBase
                    id={inputId}
                    value={textValue}
                    onChange={handleChange}
                    placeholder={field.placeholder || '{\n  "key": "value"\n}'}
                    disabled={disabled}
                    required={field.required}
                    rows={rows}
                    className=""
                    spellCheck={false}
                    aria-describedby={
                        errorToShow
                            ? `${inputId}-error`
                            : field.description
                              ? `${inputId}-desc`
                              : undefined
                    }
                    aria-invalid={hasError}
                />

                <div role="status" aria-live="polite">
                    {jsonError && (
                        <div>
                            <span
                                className="material-symbols-outlined text-error mr-1 align-middle"
                                aria-hidden="true"
                            >
                                error
                            </span>
                            {jsonError}
                        </div>
                    )}

                    {!jsonError && textValue.trim() && (
                        <div>
                            <span
                                className="material-symbols-outlined text-success mr-1 align-middle"
                                aria-hidden="true"
                            >
                                check_circle
                            </span>
                            Valid JSON
                        </div>
                    )}
                </div>
            </div>

            <FieldDescription id={`${inputId}-desc`} description={field.description} />

            <FieldError id={`${inputId}-error`} message={errorToShow} />
        </FieldWrapper>
    );
};
