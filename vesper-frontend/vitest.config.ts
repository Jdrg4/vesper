import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    globals: true,
    // 5 s por defecto no alcanza para el primer import en frio (zod) en discos
    // lentos con varios workers a la vez: `env.test.ts` fallaba solo por eso.
    testTimeout: 20_000,  },
  resolve: {
    alias: {
      "@": resolve(__dirname, "./src"),
    },
  },
});
