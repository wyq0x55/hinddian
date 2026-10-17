"""Generate 当前状态 for a project README from its most recent drafts' STATE_PATCH. usage: project_state.py <project> [N]"""
import re, sys, pathlib
sys.path.insert(0, "/opt/hinddian-classify/src")
import hinddian_batch as h
proj = sys.argv[1]; N = int(sys.argv[2]) if len(sys.argv) > 2 else 40
def ts(f): m = re.search(r"^- 时间：(\S+)", f.read_text(errors="ignore"), re.M); return m.group(1) if m else ""
dirs = [h.DRAFTS / "holdout" / proj, h.DRAFTS / proj, h.PROCESSED / proj]
fs = sorted([f for d in dirs if d.exists() for f in d.glob("*.md")], key=ts)[-N:]
chunks = []
for f in fs:
    t = f.read_text(errors="ignore")
    m = re.search(r"^## STATE_PATCH\n(.*?)(?=^## |\Z)", t, re.M | re.S)
    if m: chunks.append(f"[{ts(f)[:16]}]\n" + h.redact(m.group(1).strip()[:700]))
p = f"""根据 {proj} 项目最近 {len(chunks)} 个会话的状态片段（按时间升序，越后越新），写出项目「当前状态」。
只保留现在仍为真的内容，后面的覆盖前面的；不要逐会话流水账，不写具体行号，不写密钥。输出 Markdown，严格用这四个三级标题：
### 当前焦点
### 进行中
### 阻塞 / 待跟进
### 下一步
每节 2-5 条短 bullet。最后一行写「> 由最近会话自动汇总（截至 YYYY-MM-DD）」。只输出这段 Markdown。

""" + "\n".join(chunks)
st = h.redact(re.sub(r"^```\w*|```$", "", h.chat(p).strip(), flags=re.M).strip())
rd = h.VAULT / f"项目/{proj}/README.md"; t = rd.read_text()
if "## 当前状态" in t: t = re.sub(r"## 当前状态\n.*?(?=\n## 决策)", lambda _: "## 当前状态\n" + st + "\n", t, flags=re.S)
else: t = t.replace("\n## 决策", "\n## 当前状态\n" + st + "\n\n## 决策", 1)
h.write_file(f"项目/{proj}/README", t); h.rebuild_hubs()
print(st)
