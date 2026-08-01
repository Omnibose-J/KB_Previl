// Strip comments from TS/TSX/CSS using the real parsers, not line shapes.
//
// stdin : {"files": ["<abs path>", ...]}
// stdout: {"ok": {"<abs path>": "<stripped text>"}, "fail": {"<abs path>": "why"}}
//
// A line-shape heuristic cannot tell `// comment` from `"https://x"`, and it
// deletes `  * 3` continuation lines. Both produce code that still parses, so
// nothing downstream notices.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(
  path.join(here, "..", "frontend", "app", "package.json"),
);
const ts = require("typescript");
const postcss = require("postcss");

// Keep the line structure: a multi-line comment that vanished would move code
// onto the previous line and change automatic-semicolon insertion. The space
// keeps two tokens from fusing (`import a/**/from "x"`).
function blank(text) {
  const newlines = (text.match(/\n/g) || []).length;
  return " " + "\n".repeat(newlines);
}

function stripTs(text, file) {
  const kind = file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const source = ts.createSourceFile(
    file, text, ts.ScriptTarget.Latest, true, kind,
  );
  const ranges = new Map();
  const add = (found) => {
    if (found) for (const r of found) ranges.set(r.pos, r.end);
  };
  const walk = (node) => {
    add(ts.getLeadingCommentRanges(text, node.getFullStart()));
    add(ts.getTrailingCommentRanges(text, node.getEnd()));
    for (const child of node.getChildren(source)) walk(child);
  };
  walk(source);

  const spans = [...ranges.entries()].sort((a, b) => b[0] - a[0]);
  let out = text;
  for (const [pos, end] of spans) {
    out = out.slice(0, pos) + blank(out.slice(pos, end)) + out.slice(end);
  }
  out = out.split("\n").map((line) => line.replace(/\s+$/, "")).join("\n");
  return out.replace(/\n{3,}/g, "\n\n").replace(/^\n+/, "").replace(/\n*$/, "\n");
}

function stripCss(text, file) {
  const root = postcss.parse(text, { from: file });
  root.walkComments((node) => node.remove());
  let out = root.toString();
  // postcss keeps a comment that sits inside a value (`font-family:A/**/B`) as
  // raw text. Removing that can fuse two tokens into one, so refuse instead of
  // guessing. Check each node's own raw, with quoted strings blanked first —
  // `content: "/* x */"` is literal content, not a comment.
  const bare = (s) => (s || "").replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/g, "");
  let offender = null;
  const flag = (node, raw, what) => {
    if (!offender && bare(raw).includes("/*")) {
      offender = `${node.source && node.source.start ? node.source.start.line : "?"}행 ${what}`;
    }
  };
  root.walkDecls((d) => flag(d, (d.raws.value && d.raws.value.raw) || d.value, d.prop));
  root.walkRules((r) => flag(r, (r.raws.selector && r.raws.selector.raw) || r.selector, "선택자"));
  root.walkAtRules((r) => flag(r, (r.raws.params && r.raws.params.raw) || r.params, `@${r.name}`));
  if (offender) {
    throw new Error(
      `${offender}: 값 안에 주석이 있다. 지우면 토큰이 붙을 수 있으므로 손으로 옮길 것`,
    );
  }
  out = out.split("\n").map((line) => line.replace(/\s+$/, "")).join("\n");
  return out.replace(/\n{3,}/g, "\n\n").replace(/^\n+/, "").replace(/\n*$/, "\n");
}

const input = JSON.parse(readFileSync(0, "utf8"));
const ok = {};
const fail = {};
for (const file of input.files) {
  try {
    const text = readFileSync(file, "utf8");
    ok[file] = file.endsWith(".css") ? stripCss(text, file) : stripTs(text, file);
  } catch (err) {
    fail[file] = String((err && err.message) || err);
  }
}
process.stdout.write(JSON.stringify({ ok, fail }));
