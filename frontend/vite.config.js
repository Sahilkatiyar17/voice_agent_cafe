import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // host: true listens on all interfaces, so a Windows browser can reach the WSL server
  server: { port: 5173, host: true },
});
