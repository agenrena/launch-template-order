import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5192,
    strictPort: true,
    proxy: {
      "/api": process.env.ORDER_DEV_API ?? "http://127.0.0.1:8044",
      "/mcp": process.env.ORDER_DEV_MCP ?? "http://127.0.0.1:8768",
    },
  },
});
