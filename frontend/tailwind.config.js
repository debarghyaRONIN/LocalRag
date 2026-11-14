/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Inter"', 'system-ui', '-apple-system', 'sans-serif'],
        heading: ['"Inter"', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      colors: {
        nocturne: {
          bg: '#161826',
          surface: '#232532',
          text: '#e9e9ed',
          accent: '#9184d9',
          'accent-glow': '#a7a1db',
          section: '#262a60',
        },
        surface: {
          base: '#161826',
          panel: '#232532',
          raised: '#292b3a',
          hover: '#313445',
          border: 'rgba(233, 233, 237, 0.16)',
          subtle: 'rgba(233, 233, 237, 0.06)',
        },
        ink: {
          primary: '#e9e9ed',
          secondary: '#b2b6ca',
          muted: '#75798c',
          faint: '#3f424d',
        },
        signal: {
          green: '#9184d9',
          emerald: '#796cbf',
          amber: '#f59e0b',
          rose: '#f43f5e',
          sky: '#968ae0',
        }
      },
      letterSpacing: {
        tightest: '-0.035em',
        tighter: '-0.02em',
        tight: '-0.01em',
      }
    },
  },
  plugins: [],
}
