import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The desk is served by WebView2 from web/dist through a virtual host
// (webdesk.py: SetVirtualHostNameToFolderMapping), never by a server and
// never from file:// — so absolute "/assets/..." paths are right, and
// nothing here may reach the network at run time.
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // Rubik is 360 kB and is referenced from the repo's own fonts\
    // folder (src/styles.css); never inline it as a data: URI.
    assetsInlineLimit: 0,
    sourcemap: false,
    // WebView2 on this PC is Chromium 153; the floor is the oldest
    // runtime webdesk.precheck() accepts.
    target: "chrome110",
    modulePreload: { polyfill: false },
  },
  server: {
    // `npm run dev` is for a designer's browser only: loopback, and the
    // fonts folder one level up may be read.
    host: "127.0.0.1",
    fs: { allow: [".."] },
  },
});
