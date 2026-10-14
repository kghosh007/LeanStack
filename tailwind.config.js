/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./site/**/*.{html,js}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        wpBase: '#161413',
        wpSurface: '#1E1B19',
        wpElevated: '#282422',
        wpBorder: '#332F2C',
        wpBorderHighlight: '#4D4744',
        wpContrast: '#F7F3F2',
        wpContrast2: '#A9A6A5',
        wpContrastMuted: '#9E9A98',
        wpAccent: '#F72B00',
        wpAccentDark: '#CC1B02',
        wpAmber: '#FF6900',
        wpEmerald: '#00D084',
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      maxWidth: {
        editorial: '1380px',
      }
    },
  },
  plugins: [],
}
