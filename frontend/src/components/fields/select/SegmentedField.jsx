/**
 * SegmentedField — a settings row whose control is a segmented pill toggle.
 * Best for short either/or enums (e.g. apply_method: Kometa / Plex). Falls back
 * to the same FieldRow layout as the other simple fields.
 */

import React, { useMemo } from 'react';
import { FieldRow } from '../primitives';
import SegmentedControl from '../../ui/SegmentedControl.jsx';

export const SegmentedField = React.memo(
    ({
        field,
        value,
        onChange,
        disabled = false,
        highlightInvalid = false,
        errorMessage = null,
    }) => {
        const inputId = field.id || `field-${field.key}`;
        const options = useMemo(
            () =>
                (field.options || []).map(o =>
                    typeof o === 'string'
                        ? { value: o, label: o }
                        : { value: o.value, label: o.label || o.value }
                ),
            [field.options]
        );

        return (
            <FieldRow
                htmlFor={inputId}
                label={field.label}
                required={field.required}
                description={field.description}
                error={errorMessage}
                invalid={highlightInvalid}
            >
                <div className="flex sm:justify-end">
                    <SegmentedControl
                        options={options}
                        value={value || ''}
                        onChange={v => !disabled && onChange(v)}
                    />
                </div>
            </FieldRow>
        );
    }
);

SegmentedField.displayName = 'SegmentedField';

export default SegmentedField;
