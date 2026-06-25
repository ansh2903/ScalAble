/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './src/templates/pages/**/*.html',
    './src/templates/partials/**/*.html',
    './src/templates/pages/static/js/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        primary: '#00A36C',
        'primary-dark': '#065f46',
        'primary-soft': '#ecfdf5',
        'secondary-accent': '#475569',
        'bg-main': '#f8fafc',
        'card-border': '#e2e8f0',
        'heavy-outline': '#cbd5e1',
        'on-surface': '#1c1b1b',
        surface: '#fcf9f8',
      },
      fontFamily: {
        sans: ['Plus Jakarta Sans', 'sans-serif'],
        headline: ['Plus Jakarta Sans', 'sans-serif'],
        body: ['Plus Jakarta Sans', 'sans-serif'],
        playful: ['Fredoka', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
        script: ['Pacifico', 'cursive'],
      },
      borderRadius: {
        organic: '2.5rem',
        pill: '9999px',
        huge: '2rem',
      },
      boxShadow: {
        tactile: '0 6px 0 0 rgba(0, 163, 108, 0.2)',
        'tactile-hover': '0 3px 0 0 rgba(0, 163, 108, 0.3)',
        'data-card':
          '0 10px 25px -5px rgba(0, 0, 0, 0.04), 0 8px 10px -6px rgba(0, 0, 0, 0.04)',
        'header-nav': '0 10px 15px -3px rgba(0, 163, 108, 0.05)',
      },
      typography: (theme) => ({
        DEFAULT: {
          css: {
            '--tw-prose-links': theme('colors.primary'),
            '--tw-prose-invert-links': theme('colors.primary'),
          },
        },
      }),
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
    require('@tailwindcss/container-queries'),
    require('@tailwindcss/typography'),
  ],
};
