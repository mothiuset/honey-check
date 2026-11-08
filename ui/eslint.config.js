import js from '@eslint/js'
import { defineConfig } from 'eslint/config'
import tseslint from 'typescript-eslint'

// Límites de la interfaz. Cada bloque declara la lista completa de su zona: en ESLint, la última
// configuración que coincide con un archivo reemplaza la regla, no la suma.
const OUTER = ['@/infrastructure/**', '@/composition/**']
const REDUX = ['react-redux', '@reduxjs/toolkit']

const restrict = (patterns) => ({
  'no-restricted-imports': [
    'error',
    { patterns: patterns.map(({ group, message }) => ({ group, message })) },
  ],
})

export default defineConfig([
  { ignores: ['node_modules/**', '*.tsbuildinfo'] },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  {
    languageOptions: {
      parserOptions: {
        projectService: { allowDefaultProject: ['eslint.config.js'] },
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      '@typescript-eslint/consistent-type-definitions': ['error', 'interface'],
      '@typescript-eslint/restrict-template-expressions': [
        'error',
        { allowNumber: true },
      ],
    },
  },
  {
    files: ['src/domain/**/*.ts'],
    rules: restrict([
      {
        group: ['@/application/**', '@/presentation/**', ...OUTER],
        message: 'El dominio no depende de capas externas.',
      },
      {
        group: ['react', 'react-dom', ...REDUX],
        message: 'El dominio no conoce frameworks.',
      },
    ]),
  },
  {
    files: ['src/application/**/*.ts'],
    rules: restrict([
      {
        group: ['@/presentation/**', ...OUTER],
        message: 'La aplicación depende del dominio y de sus puertos.',
      },
      {
        group: ['react', 'react-dom', ...REDUX],
        message: 'La aplicación no conoce frameworks.',
      },
    ]),
  },
  {
    files: ['src/infrastructure/**/*.ts'],
    rules: restrict([
      {
        group: ['@/presentation/**', '@/composition/**'],
        message: 'Un adaptador no conoce la vista.',
      },
    ]),
  },
  {
    files: ['src/presentation/**/*.{ts,tsx}'],
    rules: restrict([
      {
        group: ['@/domain/**', ...OUTER],
        message: 'La presentación usa la API pública de @/application.',
      },
      {
        group: REDUX,
        message: 'Redux solo se usa dentro de presentation/store.',
      },
      {
        group: ['gsap', 'gsap/**'],
        message: 'Las animaciones viven en archivos *.gsap.ts.',
      },
    ]),
  },
  {
    files: ['src/presentation/**/*.tsx'],
    rules: {
      ...restrict([
        {
          group: ['@/domain/**', ...OUTER],
          message: 'La presentación usa la API pública de @/application.',
        },
        {
          group: REDUX,
          message: 'Redux solo se usa dentro de presentation/store.',
        },
        {
          group: ['gsap', 'gsap/**'],
          message: 'Las animaciones viven en archivos *.gsap.ts.',
        },
        {
          group: ['@/presentation/store', '@/presentation/store/**'],
          message:
            'Los componentes llegan al store solo a través de sus hooks.',
        },
      ]),
      'no-restricted-syntax': [
        'error',
        {
          selector: "JSXAttribute[name.name='style']",
          message: 'Sin estilos en línea: use el módulo CSS del componente.',
        },
      ],
    },
  },
  {
    files: ['src/presentation/store/**/*.ts'],
    rules: restrict([
      {
        group: ['@/domain/**', ...OUTER],
        message: 'El store usa la API pública de @/application.',
      },
      {
        group: ['react', 'react-dom', 'gsap', 'gsap/**'],
        message: 'El store no pinta ni anima.',
      },
    ]),
  },
  {
    files: ['src/presentation/**/*.gsap.ts'],
    rules: restrict([
      {
        group: ['@/domain/**', ...OUTER],
        message: 'La presentación usa la API pública de @/application.',
      },
      {
        group: REDUX,
        message: 'Redux solo se usa dentro de presentation/store.',
      },
    ]),
  },
])
