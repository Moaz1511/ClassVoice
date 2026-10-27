export default [
  {
    files: ['**/*.mjs'],
    ignores: ['node_modules/**'],
    rules: {
      'no-undef': 'error',
      'no-unused-vars': 'error',
    },
  },
];
