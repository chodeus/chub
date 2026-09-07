/**
 * FieldRow Primitive
 *
 * The redesign's settings row: label + description on the left, the control on
 * the right (stacks vertically on narrow viewports). Shared by the simple field
 * types (text / number / password / dropdown) so every settings form reads as a
 * dense label/control list matching the module mocks.
 */

import { FieldLabel } from './FieldLabel';
import { FieldError } from './FieldError';
import { FieldDescription } from './FieldDescription';

export const FieldRow = ({
    htmlFor,
    label,
    required = false,
    helpText,
    description,
    error = null,
    invalid = false,
    children,
}) => (
    <div className={`py-2 ${invalid ? 'text-error' : ''}`}>
        <div className="flex flex-col gap-y-2 sm:flex-row sm:items-center sm:justify-between sm:gap-x-4">
            <div className="min-w-0">
                <FieldLabel
                    htmlFor={htmlFor}
                    label={label}
                    required={required}
                    helpText={helpText}
                    className="text-sm font-medium leading-normal text-fg"
                />
                {description && (
                    <FieldDescription
                        id={htmlFor ? `${htmlFor}-desc` : undefined}
                        description={description}
                    />
                )}
            </div>
            <div className="w-full sm:w-[300px] sm:shrink-0">{children}</div>
        </div>
        {error && <FieldError id={htmlFor ? `${htmlFor}-error` : undefined} message={error} />}
    </div>
);

export default FieldRow;
