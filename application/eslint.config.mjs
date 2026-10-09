// Settings for `npx eslint static tests/test_form.js`.
//
// Two rules are off on purpose rather than because they are noisy.
//
// no-implicit-globals: the pages have no build step and no module loader.
// Buttons call their handler straight from an onclick attribute, and an
// attribute can only reach a global. Wrapping the script in an IIFE would
// hide every handler and break both pages.
//
// no-unused-vars for functions: for the same reason. ESLint cannot read an
// onclick attribute, so it reports go, send, act and the rest as unused when
// the markup is the only thing that calls them.
export default [
  {
    files: ["static/*.js", "tests/test_form.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        window: "readonly", document: "readonly", localStorage: "readonly",
        fetch: "readonly", setTimeout: "readonly", clearTimeout: "readonly", setInterval: "readonly",
        AbortController: "readonly", URL: "readonly", URLSearchParams: "readonly", console: "readonly",
        // The gate page's photo, static/gate.js.
        createImageBitmap: "readonly",
        require: "readonly", module: "readonly", __dirname: "readonly",
        process: "readonly",
        // The service worker, static/sw.js.
        self: "readonly", caches: "readonly", Request: "readonly",
      },
    },
    rules: {
      "no-undef": "error",
      "no-redeclare": "error",
      "no-dupe-keys": "error",
      "no-unreachable": "error",
      "no-fallthrough": "error",
      "no-empty": "error",
      "no-var": "error",
      "prefer-const": "error",
      "eqeqeq": "error",
      "no-unused-vars": ["error", {vars: "local", args: "after-used"}],
    },
  },
  {
    // A page function with more branches than this is split, so each part reads on one screen.
    // The tests are long lists of checks, so the limit is for the pages only.
    files: ["static/*.js"],
    rules: {complexity: ["error", 10]},
  },
];
