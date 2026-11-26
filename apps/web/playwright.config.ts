import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.AUTOAXE_E2E_PORT ?? "18173");
if (!Number.isInteger(port) || port < 1024 || port > 65535) {
  throw new Error("invalid fixture E2E port");
}
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./tests",
  use: { baseURL, ...devices["Desktop Chrome"] },
  webServer: {
    command: `pnpm preview --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: false,
  },
});
