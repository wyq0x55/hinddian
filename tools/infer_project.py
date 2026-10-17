"""Infer the real project of a 待入库 draft from entities/paths/repo names (read-only)."""
import re, sys, json, collections, pathlib

RULES = [  # (project, regexes) — scored by hit count
    ("ut-agent", [r"ut[-_]agent", r"winams", r"oracle_gap", r"golden", r"\bissue[- #]?\d+"]),
    ("slivertesttool", [r"slivertesttool", r"lan matrix"]),
    ("relaymic", [r"relaymic"]),
    ("WorkBuddy签到", [r"workbuddy", r"签到", r"猫猫"]),
    ("magpie", [r"\bmagpie\b(?!.*笔记)"]),
    ("笔记系统", [r"obsidian", r"livesync", r"hindsight", r"hinddian", r"待入库", r"vault", r"couchdb", r"session-distill", r"otlp", r"会话导出", r"提炼"]),
]
JUNK = [r"^#\s*待入库\s*·\s*(test|smoke)", r"concurrent-test"]

def infer(text: str) -> str:
    body = text.split("## DECISIONS", 1)[-1]
    t = body.lower()
    meta = re.search(r"^- 项目：(.*)$", text, re.M)
    head = (meta.group(1) if meta else "").lower()
    scores = collections.Counter()
    for proj, pats in RULES:
        for p in pats:
            n = len(re.findall(p, t))
            scores[proj] += n + (20 if re.search(p, head) else 0)
    # 笔记系统 is the wrong default tag on every draft; discount the meta line's mention
    scores["笔记系统"] -= 20 if "笔记系统" in head else 0
    if not scores or scores.most_common(1)[0][1] < 3:
        return "通用/未定"
    best = scores.most_common(1)[0][0]
    # magpie work (OTLP export, gateway, MCP) is part of the 笔记系统 pipeline unless another repo clearly wins
    return "笔记系统" if best == "magpie" else best

if __name__ == "__main__":
    d = pathlib.Path(sys.argv[1])
    res = {f.name: infer(f.read_text(errors="ignore")) for f in sorted(d.glob("*.md"))}
    json.dump(res, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
    for k, v in collections.Counter(res.values()).most_common():
        print(f"{v:5d}  {k}")
