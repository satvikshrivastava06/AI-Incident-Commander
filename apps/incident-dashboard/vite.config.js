import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // Different port from synthetic-shop-frontend's 5173, so both
    // apps can run side by side during Milestone 1.R's demo.
    port: 5174
  }
})