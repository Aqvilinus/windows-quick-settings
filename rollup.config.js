import deckyPlugin from "@decky/rollup";

// Decky's standard plugin build (React and @decky/ui mapped to Steam's copies, ESM output in dist/), with one change:
// the frontend is plain JavaScript, so the entry is src/index.js and the TypeScript step is left out.
// @decky/rollup's own defaults win over passed options, hence the edit after the call.
const config = deckyPlugin();
config.input = "./src/index.js";
config.plugins = config.plugins.filter((p) => p.name !== "typescript");

export default config;
