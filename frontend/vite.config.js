import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,                          // bind to 0.0.0.0 so ngrok can reach it
    allowedHosts: ['.ngrok-free.app'],   // allow any *.ngrok-free.app
    cors: {
      origin: ['http://localhost:5173', 'https://aac950645d56.ngrok-free.app'],
      credentials: true
    },
    proxy: {
      // Proxy everything under /api to your Flask app
      '/api': {
        target: 'http://localhost:5050',
        changeOrigin: true,
        rewrite: path => path.replace(/^\/api/, '')
      },
      // Download endpoint for PDFs
      '/download': {
        target: 'http://localhost:5050',
        changeOrigin: true
      },
      // Serve your question images
      '/images': {
        target: 'http://localhost:5050',
        changeOrigin: true
      }
    }
  }
});
