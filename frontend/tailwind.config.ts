import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  // Dark mode driven entirely by the OS/browser prefers-color-scheme media
  // query — no manual toggle needed per the spec.
  darkMode: 'media',
  theme: {
    extend: {
      // Design tokens can be added here in Phase D.
    },
  },
  plugins: [],
} satisfies Config;

