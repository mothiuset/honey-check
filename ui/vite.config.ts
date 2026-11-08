import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react-swc'
import { defineConfig } from 'vite'

// La interfaz se compila dentro del paquete de Python: el ejecutable la sirve sin internet.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  base: '/',
  build: {
    outDir: '../src/honey_check/presentation/web/dist',
    emptyOutDir: true,
    assetsDir: 'assets',
    // Sin el polyfill de modulepreload, que inyecta un script en línea prohibido por la CSP.
    modulePreload: { polyfill: false },
    chunkSizeWarningLimit: 1200,
  },
  server: {
    // Desarrollo: la API real corre en Honey Check (python -m honey_check).
    proxy: { '/api': process.env.HONEY_CHECK_API ?? 'http://127.0.0.1:8765' },
  },
})
