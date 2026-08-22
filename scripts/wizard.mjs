// Interactive OpenGSD installer wizard. Dependency-free (node:readline raw mode).
// Produces an argv for install.mjs main(); it never writes files itself.

import { emitKeypressEvents } from "node:readline";

export const HOST_LABELS = {
  codex: "Codex",
  claude: "Claude Code",
  grok: "Grok",
  opencode: "OpenCode",
  copilot: "GitHub Copilot CLI",
  qwen: "Qwen Code",
  antigravity: "Antigravity",
  cursor: "Cursor",
  zed: "Zed",
  kiro: "Kiro",
  kimi: "Kimi Code",
};

// ponytail: hand-drawn block letters; no figlet dependency.
const WORDMARK = [
  " ██████╗ ██████╗ ███████╗███╗   ██╗     ██████╗ ███████╗██████╗ ",
  "██╔═══██╗██╔══██╗██╔════╝████╗  ██║    ██╔════╝ ██╔════╝██╔══██╗",
  "██║   ██║██████╔╝█████╗  ██╔██╗ ██║    ██║  ███╗███████╗██║  ██║",
  "██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║    ██║   ██║╚════██║██║  ██║",
  "╚██████╔╝██║     ███████╗██║ ╚████║    ╚██████╔╝███████║██████╔╝",
  " ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝     ╚═════╝ ╚══════╝╚═════╝ ",
];

export function makeTheme(colored) {
  const esc = (code) => (text) => (colored ? `\u001b[${code}m${text}\u001b[0m` : text);
  const gradient = [51, 45, 39, 33, 99, 135, 171, 207]; // cyan → violet → magenta
  return {
    dim: esc("2"),
    bold: esc("1"),
    accent: esc("38;5;45"),
    ok: esc("38;5;84"),
    warn: esc("38;5;214"),
    err: esc("38;5;203"),
    inverse: esc("7"),
    gradientLine: (line, index) => (colored ? `\u001b[38;5;${gradient[index % gradient.length]}m${line}\u001b[0m` : line),
  };
}

export function banner(theme, version) {
  const lines = WORDMARK.map((line, index) => "  " + theme.gradientLine(line, index));
  lines.push("");
  lines.push(
    `  ${theme.bold("GSD Path")} ${theme.dim(`installer${version ? ` v${version}` : ""}`)}  ${theme.dim("·")}  ${theme.dim("a disk-backed pipeline for AI coding agents")}`
  );
  lines.push(`  ${theme.dim("↑/↓ move · space toggle · a all · enter confirm · q quit")}`);
  return lines.join("\n") + "\n";
}

// Reads single keypresses from `input`; resolves with {name, ctrl}.
function keyReader(input) {
  emitKeypressEvents(input);
  if (input.isTTY) input.setRawMode(true);
  input.resume();
  const queue = [];
  const waiters = [];
  input.on("keypress", (_, key) => {
    if (waiters.length) waiters.shift()(key);
    else queue.push(key);
  });
  return {
    next: () => (queue.length ? Promise.resolve(queue.shift()) : new Promise((resolve) => waiters.push(resolve))),
    close() {
      if (input.isTTY) input.setRawMode(false);
      input.pause();
    },
  };
}

class Cancelled extends Error {}

function render(output, frame, previousLines) {
  if (previousLines) output.write(`\u001b[${previousLines}A\u001b[0J`);
  output.write(frame);
  return frame.split("\n").length - 1;
}

async function select(io, theme, title, items, { multi = false, preselected = new Set() } = {}) {
  const { keys, output } = io;
  let cursor = 0;
  const chosen = new Set(preselected);
  let drawn = 0;
  const draw = () => {
    const rows = items.map((item, index) => {
      const active = index === cursor;
      const mark = multi ? (chosen.has(index) ? theme.accent("◉") : theme.dim("○")) : active ? theme.accent("›") : " ";
      const label = active ? theme.bold(item.label) : item.label;
      const note = item.note ? `  ${theme.dim(item.note)}` : "";
      return `    ${mark} ${label}${note}`;
    });
    drawn = render(output, `\n  ${theme.accent("?")} ${theme.bold(title)}\n${rows.join("\n")}\n`, drawn);
  };
  draw();
  for (;;) {
    const key = await keys.next();
    if (!key) continue;
    if (key.name === "q" || key.name === "escape" || (key.ctrl && key.name === "c")) throw new Cancelled();
    if (key.name === "up" || key.name === "k") cursor = (cursor - 1 + items.length) % items.length;
    else if (key.name === "down" || key.name === "j" || key.name === "tab") cursor = (cursor + 1) % items.length;
    else if (multi && key.name === "space") chosen.has(cursor) ? chosen.delete(cursor) : chosen.add(cursor);
    else if (multi && key.name === "a") {
      if (chosen.size === items.length) chosen.clear();
      else items.forEach((_, index) => chosen.add(index));
    } else if (key.name === "return") {
      if (multi) {
        if (!chosen.size) continue;
        draw();
        return [...chosen].sort((left, right) => left - right).map((index) => items[index].value);
      }
      draw();
      return items[cursor].value;
    }
    draw();
  }
}

const confirm = (io, theme, title, yes = "Yes", no = "No") =>
  select(io, theme, title, [
    { label: yes, value: true },
    { label: no, value: false },
  ]);

// Pure: runs the question flow and returns install.mjs argv (or null if cancelled).
// `installed(target, local)` reports whether a managed install already exists for that host in that scope.
export async function wizard({ input, output, colored = true, version = "", cwd = process.cwd(), installed = () => false, targets }) {
  const theme = makeTheme(colored);
  const keys = keyReader(input);
  const io = { keys, output };
  output.write(banner(theme, version));
  try {
    const scope = await select(io, theme, "Where should skills live?", [
      { label: "Global", value: "global", note: "per-host home directories" },
      { label: "This project", value: "local", note: cwd },
    ]);
    const local = scope === "local";

    const existing = targets.filter((target) => installed(target, local));
    const hostItems = targets.map((target) => ({
      label: HOST_LABELS[target] || target,
      value: target,
      note: existing.includes(target) ? "installed" : "",
    }));
    const preselected = new Set(existing.map((target) => targets.indexOf(target)));
    const hosts = await select(io, theme, "Which agents should get GSD Path?", hostItems, { multi: true, preselected });

    const update =
      hosts.some((host) => existing.includes(host)) &&
      (await confirm(io, theme, "Existing installs found. What do you want to do?", "Update in place", "Fresh install"));

    const project = await confirm(io, theme, "Write AGENTS.md + WORKFLOW.md contracts into this repo?", `Yes — ${cwd}`, "Not now");
    const hooks = project && (await confirm(io, theme, "Install guard hooks (archive immutability, ship-commit purity)?"));

    const argv = [];
    if (hosts.length === targets.length) argv.push("--all");
    else for (const host of hosts) argv.push(`--${host}`);
    if (update) argv.push("--update");
    if (local) argv.push("--local");
    if (project) argv.push("--project", cwd);
    if (hooks) argv.push("--hooks");
    if (!colored) argv.push("--no-color");

    output.write(`\n  ${theme.dim("Equivalent command:")}\n  ${theme.accent("$")} gsd-path ${argv.filter((arg) => arg !== "--no-color").join(" ")}\n`);
    const go = await select(io, theme, "Ready?", [
      { label: "Install", value: "install" },
      { label: "Dry run first", value: "dry", note: "preview, write nothing" },
      { label: "Quit", value: "quit" },
    ]);
    if (go === "quit") return null;
    if (go === "dry") argv.push("--dry-run");
    return argv;
  } catch (error) {
    if (error instanceof Cancelled) {
      output.write(`\n  ${theme.dim("Cancelled.")}\n`);
      return null;
    }
    throw error;
  } finally {
    keys.close();
  }
}
