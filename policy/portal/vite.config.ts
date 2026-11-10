import react from "@vitejs/plugin-react";
import { searchForWorkspaceRoot } from "vite";
import { defineConfig } from "vitest/config";

// npm run dev serves the portal on http://localhost:5173/parent/ and sends
// data requests to the stack's HTTPS parent port. POLICY_PORT picks the port.
const parentPort = process.env.POLICY_PORT ?? "8084";
// The drag-and-drop the portal shares with the child's parts of speech page lives in policy/static.
const shared = "../static";

export default defineConfig({
  base: "/parent/",
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    fs: {
      allow: [searchForWorkspaceRoot(process.cwd()), shared],
    },
    proxy: {
      "/parent/api": {
        target: `https://localhost:${parentPort}`,
        secure: false,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
