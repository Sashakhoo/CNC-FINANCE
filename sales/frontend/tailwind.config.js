/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'rgb(var(--bg) / <alpha-value>)', s1: 'rgb(var(--s1) / <alpha-value>)', s2: 'rgb(var(--s2) / <alpha-value>)', s3: 'rgb(var(--s3) / <alpha-value>)',
        line: 'rgb(var(--line) / <alpha-value>)', line2: 'rgb(var(--line2) / <alpha-value>)',
        fg: 'rgb(var(--fg) / <alpha-value>)', mute: 'rgb(var(--mute) / <alpha-value>)', dim: 'rgb(var(--dim) / <alpha-value>)',
        lime: { DEFAULT: 'rgb(var(--lime) / <alpha-value>)', hi: 'rgb(var(--lime-hi) / <alpha-value>)', soft: 'rgb(var(--lime) / 0.14)', pale: 'rgb(var(--lime-pale) / <alpha-value>)', deep: 'rgb(var(--lime-deep) / <alpha-value>)' },
        amber: { DEFAULT: 'rgb(var(--amber) / <alpha-value>)', soft: 'rgb(var(--amber) / 0.12)' },
        danger: { DEFAULT: 'rgb(var(--danger) / <alpha-value>)', soft: 'rgb(var(--danger) / 0.12)' },
        sky: { DEFAULT: 'rgb(var(--sky) / <alpha-value>)', soft: 'rgb(var(--sky) / 0.12)' },
        ink: '#1e1e1e',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        display: ['"Inter Tight"', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      borderRadius: { xl2: '20px', xl3: '28px' },
      keyframes: {
        fadein: { from: { opacity: 0, transform: 'translateY(4px)' }, to: { opacity: 1, transform: 'none' } },
        slidein: { from: { transform: 'translateX(24px)', opacity: 0 }, to: { transform: 'none', opacity: 1 } },
        shimmer: { '0%': { backgroundPosition: '-400px 0' }, '100%': { backgroundPosition: '400px 0' } },
      },
      animation: { fadein: 'fadein .25s ease-out', slidein: 'slidein .25s ease-out', shimmer: 'shimmer 1.4s linear infinite' },
    },
  },
  plugins: [],
};
