import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "../openmuse/server/static"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.node },
    },
    plugins: { "react-hooks": reactHooks },
    linterOptions: { reportUnusedDisableDirectives: "off" },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Loading data on mount and mirroring props into form state both set state from an
      // effect; the React Compiler rule forbids that, we do not run the compiler.
      "react-hooks/set-state-in-effect": "off",
      // `_x` marks an argument we have to accept but do not use
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
);
