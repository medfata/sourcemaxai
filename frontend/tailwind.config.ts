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
        ink: {
          DEFAULT: '#0A0A0A',
          50: '#F7F7F5',
          100: '#EFEEEA',
          200: '#D9D7CF',
          300: '#A8A59B',
          400: '#6B6960',
          500: '#3F3D38',
          600: '#262521',
          700: '#1A1917',
          900: '#0A0A0A',
        },
        cream: '#FFF8F4',
        accent: {
          red: '#D90429',
          coral: '#FF4D2E',
          gold: '#FFB020',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          '-apple-system',
          'BlinkMacSystemFont',
          '"SF Pro Text"',
          '"SF Pro Display"',
          'system-ui',
          'sans-serif',
        ],
        display: ['"Instrument Serif"', 'Georgia', 'serif'],
      },
      letterSpacing: {
        tight: '-0.022em',
        tighter: '-0.04em',
      },
      boxShadow: {
        ios: '0 1px 2px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.04)',
        soft: '0 1px 3px rgba(0,0,0,0.04), 0 12px 32px -8px rgba(0,0,0,0.08)',
        glow: '0 0 0 6px rgba(217, 4, 41, 0.08), 0 12px 40px -8px rgba(217, 4, 41, 0.24)',
        ring: '0 0 0 1px rgba(0,0,0,0.06), 0 24px 60px -20px rgba(0,0,0,0.18)',
      },
      backgroundImage: {
        'gradient-mesh': 'radial-gradient(at 20% 0%, rgba(217,4,41,0.18) 0px, transparent 50%), radial-gradient(at 82% 4%, rgba(255,77,46,0.16) 0px, transparent 48%), radial-gradient(at 58% 100%, rgba(255,176,32,0.12) 0px, transparent 50%)',
        'gradient-aurora': 'linear-gradient(120deg, #B8001F 0%, #FF1F3D 48%, #FFB020 100%)',
        'gradient-ink': 'linear-gradient(180deg, #FFF8F4 0%, #F4EAE4 100%)',
      },
      animation: {
        'fade-up': 'fadeUp 0.6s cubic-bezier(0.22, 1, 0.36, 1) both',
        'fade-in': 'fadeIn 0.5s ease-out both',
        'shimmer': 'shimmer 3s linear infinite',
        'float': 'float 6s ease-in-out infinite',
        'pulse-soft': 'pulseSoft 2.4s ease-in-out infinite',
      },
      keyframes: {
        fadeUp: {
          '0%': { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-12px)' },
        },
        pulseSoft: {
          '0%, 100%': { opacity: '0.6' },
          '50%': { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
} satisfies Config
