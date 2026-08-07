import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Deliberately separate from vite.config.js: pulling in the tailwind plugin
// makes every test run compile CSS for no benefit.
export default defineConfig({
    plugins: [react({ jsxRuntime: 'automatic' })],
    // Vite 8's transform doesn't inherit the plugin's JSX runtime here, so JSX
    // compiles to React.createElement and every render throws "React is not
    // defined". Set it explicitly.
    esbuild: { jsx: 'automatic' },
    test: {
        environment: 'jsdom',
        globals: true,
        setupFiles: ['./src/test/setup.js'],
        include: ['src/**/*.test.{js,jsx}'],
        restoreMocks: true,
    },
});
