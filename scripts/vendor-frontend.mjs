import { copyFile, mkdir } from "node:fs/promises";

const assets = [
  ["node_modules/htmx.org/dist/htmx.min.js", "app/static/vendor/htmx.min.js"],
  ["node_modules/@alpinejs/csp/dist/cdn.min.js", "app/static/vendor/alpine-csp.min.js"],
];

await mkdir("app/static/vendor", { recursive: true });
for (const [source, destination] of assets) {
  await copyFile(source, destination);
}
