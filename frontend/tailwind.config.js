/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          50: "#f8f7ff",
          100: "#f0eef9",
          200: "#e4e0f5",
          800: "#2a2640",
          900: "#1a1729",
          950: "#0f0d1a",
        },
        accent: {
          pink: "#ff6b9d",
          purple: "#a78bfa",
          cyan: "#67e8f9",
        },
      },
      fontFamily: {
        display: ["Segoe UI", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};