import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// Dev server proxies API + CMA pages to the Flask app on :5051.
export default defineConfig({
  plugins: [sveltekit()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:5051',
      '/cma': 'http://127.0.0.1:5051'
    }
  }
});
