import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'media',
  theme: {
    extend: {
      colors: {
        ios: {
          bg: '#F2F2F7',
          card: '#FFFFFF',
          'card-dark': '#1C1C1E',
          blue: '#007AFF',
          green: '#34C759',
          yellow: '#FF9500',
          red: '#FF3B30',
          bubble: '#E9E9EB',
          'text-primary': '#000000',
          'text-primary-dark': '#FFFFFF',
          'text-secondary': '#8E8E93',
          separator: 'rgba(198, 198, 200, 0.3)',
        },
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          '"SF Pro Text"',
          '"SF Pro Display"',
          'Inter',
          'system-ui',
          'sans-serif',
        ],
      },
      letterSpacing: {
        tight: '-0.022em',
      },
      boxShadow: {
        ios: '0 1px 2px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.04)',
      },
    },
  },
  plugins: [],
} satisfies Config
