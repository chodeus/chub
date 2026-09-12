/**
 * Error System - Composition-first error handling architecture
 *
 * Primitives (3 components):
 * - ErrorContainer, ErrorIcon, ErrorActions
 *
 * Boundaries:
 * - PageErrorBoundary (page-level errors)
 * - FeatureErrorBoundary (feature-level errors with critical/inline modes)
 *
 * Context & Hooks:
 * - ErrorProvider (global error state)
 * - useErrorContext (error reporting)
 * - useErrorRecovery (recovery actions with retry limits)
 */

export * from './primitives';
export { default as PageErrorBoundary } from './PageErrorBoundary';
export { default as FeatureErrorBoundary } from './FeatureErrorBoundary';
export { ErrorProvider, useErrorContext, useErrorRecovery } from './ErrorContext';
