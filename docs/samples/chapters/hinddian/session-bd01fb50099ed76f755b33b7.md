# hinddian · 构建章节

会话 `phase-one` · [脱敏会话记录](../../sources/session-bd01fb50099ed76f755b33b7/source.json)

引用格式为 `会话 / 位置@字符偏移`。`jsonl-N-B` 表示第 N 个来源文件的第 B 字节。

## 目标

- **已发生** 让三个宿主停止自动注入和召回历史，并保留数据与旧草稿定稿能力。（`phase-one / jsonl-1-0@0`）

## 取舍及依据

- **已发生** 优先移除启动时的注入与逐条提示词召回，保留录入与显式查询，降低迁移风险。（`phase-one / jsonl-1-785@0`）

## 关键尝试

- **已发生** 系统 Python 缺少 pytest。改用 uv 创建的临时虚拟环境安装测试依赖。（`phase-one / jsonl-1-1054@0`）

- **已发生** 两次修改测试的补丁因预期上下文不符被拒绝。（`phase-one / jsonl-1-1578@0`）

- **已发生** 中段的独立冒烟运行没读到预期 Markdown 草稿，报 FileNotFoundError。（`phase-one / jsonl-1-2358@0`）

- **推测** 缺少草稿曾使旧缓冲兼容性存疑。单次读文件失败无法确定根因。（`phase-one / jsonl-1-2358@0`）

## 取舍及依据

- **已发生** 改用宿主参数化测试与既有临时 vault fixture，通过本地 API 和固定 Jev 响应端到端验证，等待后台定稿后再读草稿。（`phase-one / jsonl-1-2697@0`）

## 验证结果

- **已发生** 三种宿主均落了新回合，并为旧会话写出含 OPEN QUESTIONS 的临时草稿。由此排除了「移除注入会一律破坏旧缓冲定稿」的假设。启动输出为零，唯一 HTTP 请求是后台定稿，全套 200 项测试通过。（`phase-one / jsonl-1-3143@0`、`phase-one / jsonl-1-3406@0`）

## OPEN QUESTIONS（未决问题）

- **待验证** 真实网关和线上宿主尚待验证。独立冒烟运行未读到草稿的确切根因也未查明。（`phase-one / jsonl-1-3406@0`）

- **待验证** 确认脱敏记录保留期、是否跨机器同步，以及 Dashboard 是否仍依赖旧 Hindsight 索引。（`phase-one / jsonl-1-3884@0`）
