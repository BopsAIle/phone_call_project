import { defineConfig } from "vite";

export default defineConfig({
  server: {
    // 0.0.0.0: Chrome/Edge trên Windows hay resolve localhost -> ::1,
    // còn Vite mặc định chỉ lắng IPv4 — Simple Browser của Cursor vẫn vào được.
    host: true,
    port: 5173,
    strictPort: true,
    proxy: {
      "/v1/bridge": { target: "http://127.0.0.1:8080", ws: true },
      "/health": { target: "http://127.0.0.1:8080" },
    },
  },
});
