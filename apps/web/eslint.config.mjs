import { globalIgnores } from 'eslint/config';

export default [
  globalIgnores(['.next/**', 'node_modules/**']),
  {
    files: ['**/*.mjs'],
    rules: {
      'no-undef': 'error',
      'no-unused-vars': 'error',
    },
  },
];
