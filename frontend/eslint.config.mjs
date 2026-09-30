import next from "eslint-config-next";
import tseslint from "typescript-eslint";

/**
 * Flat ESLint config.
 *
 * `eslint-config-next` supplies the React/Next rules; `typescript-eslint` is
 * registered explicitly so type-aware rules such as `no-explicit-any` resolve.
 */
const config = [
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "coverage/**",
      "next-env.d.ts",
      "src/generated/**",
    ],
  },
  ...next,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "no-console": ["warn", { allow: ["warn", "error"] }],
      eqeqeq: ["error", "smart"],
      "prefer-const": "error",
    },
  },
  {
    // Tests may lean on non-null assertions and stubs.
    files: ["**/*.test.{ts,tsx}", "src/test/**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-non-null-assertion": "off",
      "@typescript-eslint/no-explicit-any": "off",
    },
  },
];

export default config;
