/** @type {import('tailwindcss').Config} */
// Colours, fonts and radii come from the design-system tokens (var(--token)); no raw hex here.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        paper: 'var(--paper)',
        surface: 'var(--surface)',
        sunk: 'var(--surface-sunk)',
        rule: 'var(--rule)',
        'rule-strong': 'var(--rule-strong)',
        ink: 'var(--ink)',
        'ink-2': 'var(--ink-2)',
        'ink-3': 'var(--ink-3)',
        inverse: 'var(--inverse)',
        'on-inverse': 'var(--on-inverse)',
        accent: 'var(--accent)',
        'accent-soft': 'var(--accent-soft)',
        critical: 'var(--critical)',
        'critical-soft': 'var(--critical-soft)',
        warning: 'var(--warning)',
        'warning-soft': 'var(--warning-soft)',
        success: 'var(--success)',
        'success-soft': 'var(--success-soft)',
      },
      fontFamily: {
        serif: 'var(--font-serif)',
        sans: 'var(--font-sans)',
        mono: 'var(--font-mono)',
      },
      borderRadius: {
        xs: 'var(--radius-xs)',
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        row: 'var(--radius-row)',
        lg: 'var(--radius-lg)',
        full: 'var(--radius-full)',
      },
    },
  },
  plugins: [],
}
