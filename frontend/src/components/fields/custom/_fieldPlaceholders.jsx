/**
 * Field Placeholders
 *
 * Simple placeholder component for unimplemented field types.
 * Shows clear "not implemented" message to avoid confusion.
 */

import React from 'react';

// Simple placeholder for unimplemented field types
const UnavailableField = ({ field }) => {
    return (
        <div className="flex flex-col gap-2 mb-4 w-full">
            <label className="text-sm font-medium text-fg-muted">
                {field.label}
                {field.required && <span className="text-error ml-1">*</span>}
            </label>

            <div className="p-4 bg-surface-elevated border border-border rounded-lg text-center text-fg-subtle text-sm">
                <strong>Field type &quot;{field.type}&quot; not implemented</strong>
                <br />
                <small>This field type is not available in the current version</small>
            </div>

            {field.description && (
                <div className="text-sm text-fg-subtle mt-1">{field.description}</div>
            )}
        </div>
    );
};

// All field types - simple placeholders

// memo() of an arrow has no name, so each placeholder gets one for DevTools and display-name lint.
const placeholder = displayName => {
    const Placeholder = React.memo(props => <UnavailableField {...props} />);
    Placeholder.displayName = displayName;
    return Placeholder;
};

export const ColorField = placeholder('ColorField');
export const ColorListField = placeholder('ColorListField');

export const DirField = placeholder('DirField');
export const DirListField = placeholder('DirListField');
export const InstanceDropdownField = placeholder('InstanceDropdownField');
export const InstancesField = placeholder('InstancesField');
export const GDrivePresetsField = placeholder('GDrivePresetsField');
export const HolidayPresetsField = placeholder('HolidayPresetsField');
export const HolidayScheduleField = placeholder('HolidayScheduleField');
export const DirListDragDropField = placeholder('DirListDragDropField');
export const DirListOptionsField = placeholder('DirListOptionsField');

// Additional field types from original vision - currently placeholders
// TagSelectField and TagDisplayField replaced by tag_input and tag_display field types
// which use the configurable TagInputField component
// export const TagSelectField = React.memo(props => <UnavailableField {...props} />);
// export const TagDisplayField = React.memo(props => <UnavailableField {...props} />);
export const TagMultiSelectField = placeholder('TagMultiSelectField');
export const MediaInfoDisplayField = placeholder('MediaInfoDisplayField');
export const MediaDisplayField = placeholder('MediaDisplayField');
export const DirPickerField = placeholder('DirPickerField');
export const PosterField = placeholder('PosterField');
