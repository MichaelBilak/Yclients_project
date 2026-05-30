import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

const rootDir = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig({
  appType: 'mpa',
  build: {
    rollupOptions: {
      input: {
        main: resolve(rootDir, 'index.html'),
        login: resolve(rootDir, 'login.html'),
        register: resolve(rootDir, 'register.html'),
        forgot: resolve(rootDir, 'forgot-password.html'),
        reset: resolve(rootDir, 'reset-password.html'),
        verify: resolve(rootDir, 'verify-email.html'),
        profile: resolve(rootDir, 'profile.html'),
        admin: resolve(rootDir, 'admin.html'),
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/auth': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/dashboard': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
