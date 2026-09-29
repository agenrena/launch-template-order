// Colours live only in src/theme.css. Everything else must use its variables,
// so changing the brand or adding a theme never means hunting for literals.
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

const root = new URL("../src/", import.meta.url).pathname;
const allowed = new Set(["theme.css"]);
const colour =
  /#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab|lab|lch)\(|\bcolor-mix\(/gi;

function* files(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) yield* files(path);
    else if (/\.(css|tsx?)$/.test(entry.name)) yield path;
  }
}

const problems = [];
for (const path of files(root)) {
  const name = relative(root, path);
  if (allowed.has(name)) continue;
  readFileSync(path, "utf8")
    .split("\n")
    .forEach((line, i) => {
      // Skip JSX entities such as &#10003; and comments.
      const code = line.replace(/&#\w+;/g, "").replace(/\/\/.*$|\/\*.*?\*\//g, "");
      for (const match of code.matchAll(colour))
        problems.push(`src/${name}:${i + 1}  ${match[0]}`);
    });
}

if (problems.length) {
  console.error(
    "Colours must come from src/theme.css variables (var(--…)):\n" +
      problems.map((p) => "  " + p).join("\n"),
  );
  process.exit(1);
}
console.log("check:style ok — no colour literals outside src/theme.css");
