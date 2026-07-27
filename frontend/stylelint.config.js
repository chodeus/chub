export default {
  extends: ['stylelint-config-standard'],
  overrides: [
    {
      // Tailwind v4 entry: allow its at-rules, nested @utility bodies, and
      // its bare-string @import of the engine layers.
      files: ['src/css/tailwind.css'],
      rules: {
        'at-rule-no-unknown': [
          true,
          {
            ignoreAtRules: [
              'theme',
              'utility',
              'source',
              'custom-variant',
              'variant',
              'apply',
              'reference',
              'config',
              'plugin',
            ],
          },
        ],
        'at-rule-empty-line-before': null,
        'rule-empty-line-before': null,
        'nesting-selector-no-missing-scoping-root': null,
        'import-notation': null,
        'selector-class-pattern': null,
        'custom-property-pattern': null,
        'value-keyword-case': null,
      },
    },
  ],
  rules: {
    'selector-class-pattern': [
      '^(?:[a-z0-9]+(?:-[a-z0-9]+)*(?:__(?:[a-z0-9]+(?:-[a-z0-9]+)*))?(?:--(?:[a-z0-9]+(?:-[a-z0-9]+)*))?|(?:sm|md|lg|xl)\\:[a-z0-9-]+|[a-z0-9-]+\\/[0-9])$',
      {
        message:
          'Class selectors should be written in BEM (block__element--modifier) style (lowercase, no special chars except _ and -), or be utility classes.',
      },
    ],
    'selector-id-pattern': null,
    'max-nesting-depth': 2,
  },
};