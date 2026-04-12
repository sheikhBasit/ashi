import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30000,
  use: {
    // Tauri WebDriver endpoint
    browserName: "chromium",
  },
  // Custom webServer for Tauri
  webServer: {
    command: "cargo tauri dev",
    url: "http://localhost:1420",
    reuseExistingServer: true,
    timeout: 120000,
    cwd: ".",
  },
});
