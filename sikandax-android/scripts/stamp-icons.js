// Stamps the gold SX launcher icon into the generated android/ project.
// Runs in CI after `npx cap add android` (android/ is gitignored and rebuilt).
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const src = path.join(root, "assets", "icon.png");
const res = path.join(root, "android", "app", "src", "main", "res");
const dirs = ["mipmap-mdpi", "mipmap-hdpi", "mipmap-xhdpi", "mipmap-xxhdpi", "mipmap-xxxhdpi"];

if (!fs.existsSync(src)) { console.error("missing assets/icon.png"); process.exit(1); }
if (!fs.existsSync(res)) { console.error("android/ not generated yet — run `npx cap add android` first"); process.exit(1); }
for (const d of dirs) {
  const dir = path.join(res, d);
  if (!fs.existsSync(dir)) continue;
  fs.copyFileSync(src, path.join(dir, "ic_launcher.png"));
  fs.copyFileSync(src, path.join(dir, "ic_launcher_round.png"));
  console.log("stamped", d);
}
