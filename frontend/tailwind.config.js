/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,jsx,ts,tsx}", "./public/index.html"],
  theme: {
    extend: {
      colors: {
        btc: "#F7931A",
        "btc-dark": "#C17316",
        green: {
          400: "#4ade80",
          500: "#22c55e",
          900: "#14532d",
        },
        red: {
          400: "#f87171",
          500: "#ef4444",
          900: "#7f1d1d",
        },
        dark: {
          50: "#1a1a2e",
          100: "#16213e",
          200: "#0f3460",
          300: "#1e1e2e",
          400: "#252535",
          500: "#2d2d44",
        },
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "blink-green": "blinkGreen 1s ease-in-out 3",
        "blink-red": "blinkRed 1s ease-in-out 3",
      },
      keyframes: {
        blinkGreen: {
          "0%, 100%": { color: "#4ade80" },
          "50%": { color: "#86efac" },
        },
        blinkRed: {
          "0%, 100%": { color: "#f87171" },
          "50%": { color: "#fca5a5" },
        },
      },
    },
  },
  plugins: [],
};
