"""Render a recorded Claude Code session into an animated terminal SVG.

    claude -p "<question>" --allowedTools "mcp__thehub__*" \
        --output-format stream-json --verbose > raw.jsonl
    python docs/demo/render.py raw.jsonl "<question>"

Writes docs/demo/transcript.json (only the question, tool calls, results and
answer; the raw stream also lists local paths and other MCP servers) and
docs/demo/demo.svg, which GitHub shows inline in the README.
"""
from __future__ import annotations

import json
import sys
import textwrap
from html import escape
from pathlib import Path

HERE = Path(__file__).parent
WIDTH_CHARS = 88
CHAR_W, LINE_H, PAD = 8.6, 20, 18  # wide enough for Menlo, SF Mono and Consolas
STEP = 0.12  # seconds between answer lines
BG, FG, DIM, ACCENT, GREEN, BAR = "#0d1117", "#e6edf3", "#8b949e", "#d2a8ff", "#7ee787", "#161b22"


def trim(raw: Path, question: str) -> dict:
    steps = []
    for line in raw.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event["type"] == "assistant":
            for block in event["message"]["content"]:
                if block["type"] == "tool_use" and block["name"].startswith("mcp__thehub__"):
                    steps.append({"tool": block["name"].removeprefix("mcp__thehub__"), "input": block["input"]})
                elif block["type"] == "text":
                    steps.append({"answer": block["text"]})
        elif event["type"] == "user":
            for block in event["message"]["content"]:
                if block.get("type") == "tool_result" and steps and "tool" in steps[-1]:
                    content = block["content"]
                    text = content if isinstance(content, str) else content[0].get("text", "")
                    steps[-1]["result"] = json.loads(text)
    return {"question": question, "steps": steps}


def result_line(result) -> str:
    if isinstance(result, dict) and "companies" in result:
        names = ", ".join(c["name"].strip() for c in result["companies"][:4])
        return f'{{"total": {result["total"]}, "companies": [{names}, …]}}'
    return json.dumps(result, ensure_ascii=False)[: WIDTH_CHARS - 6]


def lines_for(transcript: dict) -> list[tuple[str, str, float]]:
    """(css class, text, seconds after start) for every terminal line."""
    out: list[tuple[str, str, float]] = []
    t = 0.4
    out.append(("prompt", f"> {transcript['question']}", t))
    t += 1.4
    for step in transcript["steps"]:
        if "tool" in step:
            args = ", ".join(f"{k}={json.dumps(v)}" for k, v in step["input"].items())
            out.append(("", "", t))
            call = textwrap.wrap(f"⏺ thehub · {step['tool']}({args})", WIDTH_CHARS, subsequent_indent="    ")
            out += [("tool", text, t) for text in call]
            t += 1.2
            out.append(("dim", f"  ⎿  {result_line(step.get('result'))}", t))
            t += 1.0
        else:
            out.append(("", "", t))
            for para in step["answer"].splitlines():
                wrapped = textwrap.wrap(para.replace("**", ""), WIDTH_CHARS - 4,
                                        subsequent_indent="    " if para.startswith("- ") else "") or [""]
                for i, text in enumerate(wrapped):
                    out.append(("answer", ("⏺ " if not out[-1][1] and i == 0 else "  ") + text, t))
                    t += STEP
    return out


def svg(lines: list[tuple[str, str, float]]) -> str:
    width = int(WIDTH_CHARS * CHAR_W + 2 * PAD)
    top = 36
    height = top + PAD + LINE_H * len(lines) + PAD
    rows = []
    for i, (cls, text, at) in enumerate(lines):
        y = top + PAD + LINE_H * (i + 0.75)
        rows.append(
            f'<text x="{PAD}" y="{y:.0f}" class="l {cls}" style="animation-delay:{at:.2f}s">'
            f"{escape(text)}</text>"
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Claude Code answering a question with the thehub MCP server">
<style>
  .l {{ font: 13.5px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; fill: {FG}; white-space: pre; opacity: 0; animation: in .25s ease-out forwards; }}
  .prompt {{ fill: {GREEN}; font-weight: 600; }}
  .tool {{ fill: {ACCENT}; }}
  .dim {{ fill: {DIM}; }}
  @keyframes in {{ to {{ opacity: 1; }} }}
  @media (prefers-reduced-motion: reduce) {{ .l {{ animation: none; opacity: 1; }} }}
</style>
<rect width="{width}" height="{height}" rx="10" fill="{BG}"/>
<rect width="{width}" height="{top}" rx="10" fill="{BAR}"/>
<rect y="{top - 10}" width="{width}" height="10" fill="{BAR}"/>
<circle cx="20" cy="18" r="6" fill="#ff5f57"/><circle cx="40" cy="18" r="6" fill="#febc2e"/><circle cx="60" cy="18" r="6" fill="#28c840"/>
<text x="{width / 2}" y="23" text-anchor="middle" style="font: 12px ui-monospace, Menlo, monospace; fill: {DIM}">claude — thehub MCP server</text>
{chr(10).join(rows)}
</svg>
"""


def main() -> None:
    if len(sys.argv) == 3:
        transcript = trim(Path(sys.argv[1]), sys.argv[2])
        (HERE / "transcript.json").write_text(json.dumps(transcript, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        transcript = json.loads((HERE / "transcript.json").read_text(encoding="utf-8"))
    (HERE / "demo.svg").write_text(svg(lines_for(transcript)), encoding="utf-8")


if __name__ == "__main__":
    main()
