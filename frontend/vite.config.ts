import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/index": "http://localhost:8000",
      "/search": "http://localhost:8000",
      "/metrics": "http://localhost:8000",
      "/jobs": "http://localhost:8000",
      "/settings": "http://localhost:8000",
      "/embeddings": "http://localhost:8000"
    }
  }
});

