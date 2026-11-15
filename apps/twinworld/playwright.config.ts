import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:5173",
    headless: true,
    launchOptions: {
      executablePath: process.env.ENOM_BROWSER_PATH || undefined,
      args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
    },
  },
  webServer: [
    { command: "../../.venv/bin/uvicorn twinworld.api:app --host 127.0.0.1 --port 8000", url: "http://127.0.0.1:8000/api/health", reuseExistingServer: true, timeout: 20_000 },
    { command: "npm run dev", url: "http://127.0.0.1:5173", reuseExistingServer: true, timeout: 20_000 },
  ],
});
