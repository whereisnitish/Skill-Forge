// Copy pinned third-party browser assets from node_modules into static/ so
// production never depends on a CDN, and vendor only the Lucide icons that
// templates, Python code and catalogue content actually reference.
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const nm = join(root, "node_modules");

const files = [
  ["htmx.org/dist/htmx.min.js", "static/vendor/htmx.min.js"],
  ["chart.js/dist/chart.umd.min.js", "static/vendor/chart.umd.min.js"],
  ["@fontsource-variable/inter/files/inter-latin-wght-normal.woff2", "static/fonts/inter-latin-wght-normal.woff2"],
  ["@fontsource-variable/inter/files/inter-latin-wght-italic.woff2", "static/fonts/inter-latin-wght-italic.woff2"],
  ["@fontsource/dm-serif-display/files/dm-serif-display-latin-400-normal.woff2", "static/fonts/dm-serif-display-latin-400-normal.woff2"],
  ["@fontsource/dm-serif-display/files/dm-serif-display-latin-400-italic.woff2", "static/fonts/dm-serif-display-latin-400-italic.woff2"],
  ["@fontsource-variable/jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2", "static/fonts/jetbrains-mono-latin-wght-normal.woff2"],
];

for (const [src, dest] of files) {
  const target = join(root, dest);
  mkdirSync(dirname(target), { recursive: true });
  copyFileSync(join(nm, src), target);
}

// Collect icon names referenced anywhere in templates, app code and content.
const scanDirs = ["templates", "apps"];
const patterns = [
  /\{%\s*icon\s+"([a-z0-9-]+)"/g,
  /icon\s*[:=]\s*["']([a-z0-9-]+)["']/g,
  /["']icon["']\s*:\s*["']([a-z0-9-]+)["']/g,
  /AchievementDef\([^)]*?,\s*"([a-z0-9-]+)"\s*\)/gs,
  /: "([a-z0-9-]+)",?\s*#\s*icon/g,
  /^\s*icon:\s*([a-z0-9-]+)\s*$/gm, // unquoted YAML (catalogue categories and paths)
];
const extra = [
  "list-checks", "text-cursor-input", "code-xml", "bug", "message-square-text", "git-pull-request",
  "lightbulb", "messages-square", "puzzle", "file-code-2", "briefcase", "server", "brain-circuit",
  "network", "message-circle-more", "shapes", "database", "binary", "route", "zap", "footprints",
  "flame", "calendar-check", "target", "trending-up", "gem", "brain", "rotate-ccw",
];
const names = new Set(extra);

function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const stats = statSync(full);
    if (stats.isDirectory()) {
      if (["node_modules", "migrations", "__pycache__", "icons"].includes(entry)) continue;
      walk(full);
    } else if (/\.(html|py|yaml|txt)$/.test(entry)) {
      const text = readFileSync(full, "utf8");
      for (const pattern of patterns) {
        for (const match of text.matchAll(pattern)) names.add(match[1]);
      }
    }
  }
}
for (const dir of scanDirs) walk(join(root, dir));

const iconSrc = join(nm, "lucide-static/icons");
const iconDest = join(root, "apps/core/icons");
mkdirSync(iconDest, { recursive: true });
const missing = [];
for (const name of [...names].sort()) {
  const src = join(iconSrc, `${name}.svg`);
  if (existsSync(src)) copyFileSync(src, join(iconDest, `${name}.svg`));
  else missing.push(name);
}
writeFileSync(
  join(iconDest, "LICENSE.txt"),
  readFileSync(join(nm, "lucide-static/LICENSE"), "utf8"),
);
console.log(`Vendored ${files.length} files and ${names.size - missing.length} icons into ${relative(root, iconDest)}.`);
if (missing.length) console.log(`Not icons (ignored): ${missing.join(", ")}`);
