// Strip comments from TS/TSX/CSS using the real parsers, not line shapes.
//
// stdin : {"files": ["<abs path>", ...]}
// stdout: {"ok": {"<abs path>": "<stripped text>"}, "fail": {"<abs path>": "why"}}
//
// A line-shape heuristic cannot tell `// comment` from `"https://x"`, and it
// deletes `  * 3` continuation lines. Both produce code that still parses, so
// nothing downstream notices.
//
// Two comments are not decoration and must never be dropped silently:
// compiler/bundler pragmas and legal notices. Those refuse the build instead.
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

// Comments the toolchain reads. Removing one keeps the file parsing while
// changing what is compiled, bundled, or legally required. `eslint-disable`
// and `prettier-ignore` are deliberately absent: neither runs on the shipped
// tree, so dropping them cannot change the built output.
const SEMANTIC = [
  [/^\/[*/]!/, "보존 표시(/*!)"],
  [/^\/\/\/\s*</, "triple-slash directive"],
  [/[@#]__PURE__/, "purity annotation"],
  [/@ts-(ignore|expect-error|nocheck|check)/, "TypeScript directive"],
  [/@(license|preserve|copyright)/i, "legal notice"],
  [/@jsx(Runtime|ImportSource|Frag)?\b/, "JSX pragma"],
  [/@vite-ignore|webpack[A-Z]\w+|magic-comment/, "bundler magic comment"],
  [/sourceMappingURL|sourceURL/, "source-map link"],
  [/@flow\b/, "Flow pragma"],
];

function semantic(text) {
  for (const [pattern, what] of SEMANTIC) {
    if (pattern.test(text)) return what;
  }
  return null;
}

function lineOf(text, pos) {
  return text.slice(0, pos).split("\n").length;
}

// Keep the line structure: a multi-line comment that vanished would move code
// onto the previous line and change automatic-semicolon insertion. The space
// keeps two tokens from fusing (`import a/**/from "x"`).
function blank(text) {
  const newlines = (text.match(/\n/g) || []).length;
  return " " + "\n".repeat(newlines);
}

function tidy(out) {
  out = out.split("\n").map((line) => line.replace(/\s+$/, "")).join("\n");
  return out.replace(/\n{3,}/g, "\n\n").replace(/^\n+/, "").replace(/\n*$/, "\n");
}

// Independent check: ask the parser what text sits between tokens rather than
// which comments it found. Anything that is not whitespace there is leftover.
// This does not consult the comment-range API the removal used, so a blind spot
// in that API still shows up here — re-running the same stripper could not.
// A raw scanner was the obvious alternative and is wrong: it desyncs inside
// `${...}` templates and reports the tail as a comment.
function residualTrivia(text, file) {
  const kind = file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const source = ts.createSourceFile(
    file, text, ts.ScriptTarget.Latest, true, kind,
  );
  let at = -1;
  const walk = (node) => {
    const kids = node.getChildren(source);
    if (!kids.length) {
      const start = node.getStart(source, false);
      const found = text.slice(node.getFullStart(), start).search(/\S/);
      if (found >= 0 && at < 0) at = node.getFullStart() + found;
    }
    for (const kid of kids) walk(kid);
  };
  walk(source);
  return at;
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
  for (const [pos, end] of spans) {
    const what = semantic(text.slice(pos, end).trim());
    if (what) {
      throw new Error(
        `${lineOf(text, pos)}행 ${what} — 지우면 컴파일·번들 결과가 달라진다. `
        + "코드로 옮기거나 이 파일을 출하 목록에서 뺄 것",
      );
    }
  }
  let out = text;
  for (const [pos, end] of spans) {
    out = out.slice(0, pos) + blank(out.slice(pos, end)) + out.slice(end);
  }
  out = tidy(out);
  const left = residualTrivia(out, file);
  if (left >= 0) {
    throw new Error(`${lineOf(out, left)}행 주석이 남았다 — 제거기가 놓쳤다`);
  }
  return out;
}

// Quoted strings are content, not syntax: `content: "/* keep */"` is literal
// text a rule prints, and `url("a/*b")` is a path.
const bare = (s) => (s || "").replace(
  /"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/g, "",
);

function stripCss(text, file) {
  const root = postcss.parse(text, { from: file });
  root.walkComments((node) => {
    if (node.text.startsWith("!") || semantic(`/*${node.text}*/`)) {
      throw new Error(
        `${node.source.start.line}행 보존 주석 — 지우면 안 되는 표시가 붙어 있다`,
      );
    }
    node.remove();
  });
  let out = tidy(root.toString());
  // postcss parks a comment that sits inside a value, a selector, or between a
  // property and its colon in `raws`, where walkComments never sees it. Check
  // the finished text instead of asking the AST — `.a{color/**/:red}` survived
  // every AST-side check and the idempotence test agreed with it twice.
  const lines = bare(out).split("\n");
  const at = lines.findIndex((line) => line.includes("/*"));
  if (at >= 0) {
    throw new Error(
      `${at + 1}행: 값·선택자 안에 주석이 있다. 지우면 토큰이 붙을 수 있으므로 `
      + "손으로 옮긴 뒤 다시 빌드할 것",
    );
  }
  return out;
}

// utf-8 with replacement characters would ship a different string literal than
// the source holds. Refuse instead.
function read(file) {
  return new TextDecoder("utf-8", { fatal: true }).decode(readFileSync(file));
}

const input = JSON.parse(readFileSync(0, "utf8"));
const ok = {};
const fail = {};
for (const file of input.files) {
  try {
    const text = read(file);
    ok[file] = file.endsWith(".css") ? stripCss(text, file) : stripTs(text, file);
  } catch (err) {
    fail[file] = String((err && err.message) || err);
  }
}
process.stdout.write(JSON.stringify({ ok, fail }));
