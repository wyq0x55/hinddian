/**
 * Magpie plugin: expose install/status tools for hinddian Library Hooks + MCP.
 *
 * Hard limit: Magpie plugin packages cannot declare Library Hooks in a way that
 * WebDAV/marketplace auto-registers them. Enabling this plugin does NOT write
 * library.json hooks by itself — call the install tool (or run install.ps1).
 *
 * Optional Magpie adapter only — hinddian core is Claude/Codex first.
 * Install:  magpie plugin add github:wyq0x55/hinddian  (root package.json shims here)
 * Then:     ask an agent to run hinddian_install, or run install.ps1
 */
import { tool } from "@opencode-ai/plugin"
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, "..")

function skillDirs() {
  return [
    path.join(ROOT, "skills", "hinddian-hooks"),
    path.join(ROOT, "..", "..", "skills", "hinddian-hooks"),
  ]
}

function findInstallPy() {
  for (const d of skillDirs()) {
    const p = path.join(d, "install.py")
    if (fs.existsSync(p)) return p
  }
  return null
}

function runPython(script, args = []) {
  const candidates = process.platform === "win32"
    ? [["py", ["-3", script, ...args]], ["python", [script, ...args]], ["python3", [script, ...args]]]
    : [["python3", [script, ...args]], ["python", [script, ...args]]]
  let last = null
  for (const [bin, a] of candidates) {
    const r = spawnSync(bin, a, { encoding: "utf8", env: process.env })
    if (r.error && r.error.code === "ENOENT") {
      last = r
      continue
    }
    return {
      ok: r.status === 0,
      status: r.status,
      stdout: (r.stdout || "").trim(),
      stderr: (r.stderr || "").trim(),
      bin,
    }
  }
  return {
    ok: false,
    status: -1,
    stdout: "",
    stderr: `Python not found. Last error: ${last?.error?.message || "none"}`,
    bin: null,
  }
}

export const HinddianMagpie = async () => ({
  tool: {
    hinddian_install: tool({
      description:
        "Install hinddian on THIS Magpie: write Library Hooks (session-start/turn-end) + MCP hinddian-memory. WebDAV does not sync Hooks — run once per PC. Prefer this over editing library.json by hand.",
      args: {},
      async execute() {
        const py = findInstallPy()
        if (!py) {
          return JSON.stringify({
            ok: false,
            error: "install.py not found in plugin package (skills/hinddian-hooks).",
            hint: "magpie plugin update hinddian-magpie, or install skill from GitHub wyq0x55/hinddian",
          })
        }
        const r = runPython(py)
        if (r.ok) {
          spawnSync("magpie", ["library", "sync"], { encoding: "utf8" })
        }
        return JSON.stringify({
          ok: r.ok,
          install_py: py,
          python: r.bin,
          status: r.status,
          stdout: r.stdout.slice(0, 4000),
          stderr: r.stderr.slice(0, 2000),
          next: r.ok
            ? "Open Magpie → Library → Hooks: hinddian-session-start, hinddian-turn-end. MCP: hinddian-memory."
            : "Fix Python/PATH, or run %USERPROFILE%\\.config\\magpie\\library\\skills\\hinddian-hooks\\install.ps1 on Windows.",
        })
      },
    }),
    hinddian_status: tool({
      description: "Check whether hinddian Magpie Hooks and hinddian-memory MCP are present in local library.json.",
      args: {},
      async execute() {
        const homes = []
        if (process.env.XDG_CONFIG_HOME) homes.push(path.join(process.env.XDG_CONFIG_HOME, "magpie"))
        homes.push(path.join(process.env.HOME || process.env.USERPROFILE || "", ".config", "magpie"))
        if (process.env.APPDATA) homes.push(path.join(process.env.APPDATA, "magpie"))
        if (process.env.LOCALAPPDATA) homes.push(path.join(process.env.LOCALAPPDATA, "magpie"))
        if (process.env.MAGPIE_LIBRARY) homes.push(path.dirname(process.env.MAGPIE_LIBRARY))

        let libPath = null
        for (const h of homes) {
          const p = path.join(h, "library.json")
          if (fs.existsSync(p)) {
            libPath = p
            break
          }
        }
        if (!libPath) {
          return JSON.stringify({ ok: false, error: "library.json not found", checked: homes })
        }
        const data = JSON.parse(fs.readFileSync(libPath, "utf8"))
        const hooks = (data.hooks || []).map((h) => h.name)
        const mcp = (data.mcp || []).map((m) => m.name)
        const need = ["hinddian-session-start", "hinddian-turn-end"]
        const hasHooks = need.every((n) => hooks.includes(n))
        const hasMcp = mcp.includes("hinddian-memory")
        return JSON.stringify({
          ok: true,
          library: libPath,
          hooks_ok: hasHooks,
          mcp_ok: hasMcp,
          hooks: hooks.filter((n) => String(n).startsWith("hinddian")),
          mcp: mcp.filter((n) => n === "hinddian-memory" || n === "hindsight"),
          install_py: findInstallPy(),
          advice: hasHooks && hasMcp
            ? "Installed. New Magpie session to exercise hooks."
            : "Call hinddian_install once on this PC.",
        })
      },
    }),
  },
})
