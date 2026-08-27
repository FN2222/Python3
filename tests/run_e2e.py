"""端到端自测:合成 PDF -> 抽取 -> 任务包 -> 注入示例 note.json -> 校验 -> 渲染 -> Markdown。

    python tests/run_e2e.py

同时验证"反臆想门禁"确实会拦住编造内容(negative case)。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / "tests" / "_tmp"
SRC = TMP / "source"
BUILD = TMP / "build"
NOTES = TMP / "notes"
PY = sys.executable

COMMON = ["--source-root", str(SRC), "--build-dir", str(BUILD), "--notes-dir", str(NOTES)]
FAILURES: list[str] = []


def run(args: list[str], expect_rc: int | None = 0) -> subprocess.CompletedProcess:
    proc = subprocess.run([PY, "-m", "nlnotes", *args], cwd=ROOT,
                          capture_output=True, text=True)
    tag = " ".join(args[:2])
    if expect_rc is not None and proc.returncode != expect_rc:
        FAILURES.append(f"命令 `{tag}` 返回码 {proc.returncode},期望 {expect_rc}\n"
                        f"{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}")
    return proc


def check(cond: bool, msg: str) -> None:
    print(f"  {'✅' if cond else '❌'} {msg}")
    if not cond:
        FAILURES.append(msg)


def main() -> int:
    shutil.rmtree(TMP, ignore_errors=True)

    print("\n[1/7] 生成合成课程 PDF")
    sys.path.insert(0, str(ROOT / "tests"))
    from make_sample_pdf import build
    pdf = build(SRC)
    before = pdf.stat().st_mtime, pdf.stat().st_size

    print("\n[2/7] scan + extract + tasks")
    run(["prepare", *COMMON])
    manifest = json.loads((BUILD / "manifest.json").read_text(encoding="utf-8"))
    pdf_id = manifest["items"][0]["id"]
    check(manifest["count"] == 1, "扫描到 1 个 PDF")
    meta = json.loads((BUILD / "extract" / pdf_id / "extract.json").read_text(encoding="utf-8"))
    check(meta["pages_total"] == 4, f"抽取到 4 页(实际 {meta['pages_total']})")
    check(meta["figure_count"] == 2, f"抽取到 2 张拓扑图(实际 {meta['figure_count']})")
    check(meta["codeblock_count"] >= 1, "识别到 CLI 配置块")
    task = BUILD / "tasks" / pdf_id
    for f in ("TASK.md", "source-text.md", "figures.md", "glossary.md",
              "codeblocks.md", "context.json", "note.schema.json", "note.template.json"):
        check((task / f).exists(), f"任务包含 {f}")

    print("\n[3/7] 注入示例 note.json(模拟 AI 产出)")
    note = json.loads((ROOT / "tests" / "fixtures" / "sample-note.json").read_text(encoding="utf-8"))
    note["pdf_id"] = pdf_id
    out = task / "OUTPUT" / "note.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n[4/7] 正例:校验应当通过")
    proc = run(["build", "--id", pdf_id, *COMMON])
    report = json.loads((BUILD / "reports" / f"{pdf_id}.json").read_text(encoding="utf-8"))
    if not report["passed"]:
        print(json.dumps(report["errors"], ensure_ascii=False, indent=2)[:4000])
    check(report["passed"], "示例 note.json 通过门禁")
    check(report["stats"]["quotes_checked"] == report["stats"]["quotes_matched"],
          f"全部引用命中原文 ({report['stats']['quotes_matched']}/{report['stats']['quotes_checked']})")
    check(report["stats"]["coverage_ratio"] >= 0.8,
          f"覆盖率 {report['stats']['coverage_ratio']:.0%} ≥ 80%")

    print("\n[5/7] 检查产物")
    md = NOTES / manifest["items"][0]["note_rel_path"]
    check(md.exists(), f"生成 Markdown: {md.relative_to(ROOT)}")
    text = md.read_text(encoding="utf-8")
    for needle, desc in [
        ("费曼学习法检验", "含费曼测验章节"),
        ("参考答案 / Answers", "含双语答案区"),
        ("fig-p001-1.png", "引用了原文拓扑图"),
        ("v1.gif", "引用了自制动画 GIF"),
        ("v1-steps.png", "引用了分步静态图"),
        ("stateDiagram-v2", "内联了 mermaid 状态机(未装 mermaid-cli 时的降级)"),
        ("| 判定顺序 |", "渲染了对比表格"),
        ("show ip ospf neighbor", "逐字保留了 CLI 输出"),
        ("原文依据", "每张自制图附带原文依据"),
    ]:
        check(needle in text, desc)
    assets = md.parent / "assets" / pdf_id
    gif = assets / "v1.gif"
    check(gif.exists() and gif.stat().st_size > 5000, f"动画 GIF 已生成({gif.stat().st_size if gif.exists() else 0} 字节)")
    check((assets / "v1-steps.png").exists(), "分步静态图已生成")
    check((assets / "fig-p001-1.png").exists(), "原文配图已复制到 assets")
    check((NOTES / "README.md").exists(), "生成全局索引 notes/README.md")

    print("\n[6/7] 反例:门禁必须拦住编造内容")
    cases = {
        "编造的定时器数值": lambda n: n["sections"][0]["points"][3].update(
            {"text_zh": "dead interval 默认是 120 秒,是 hello interval 的四倍。"}),
        "编造的协议名": lambda n: n["sections"][0]["points"][0].update(
            {"text_zh": "OSPF 路由器靠 hello 报文发现邻居,这一点和 FooBarProtocol 一样。"}),
        "引用不是原文": lambda n: n["sections"][0]["points"][0].update(
            {"text_en_quote": "OSPF routers exchange gossip messages to find their friends."}),
        "页码写错": lambda n: n["sections"][0]["points"][0].update({"page": 3}),
        "不存在的图": lambda n: n["sections"][0]["figures"][0].update({"figure_id": "fig-p099-1"}),
        "发散措辞": lambda n: n.update({"summary_zh": n["summary_zh"] + " 笔者认为这在生产环境很重要。"}),
        "题目数量不足": lambda n: n["feynman"].update({"questions": n["feynman"]["questions"][:3]}),
        "英文答案混入中文": lambda n: n["feynman"]["questions"][0].update(
            {"answer_en": "They use hello 报文."}),
        "覆盖度不足": lambda n: n.update({"sections": n["sections"][:1]}),
        "自制图依据不是原文": lambda n: n["sections"][0]["visuals"][0].update(
            {"grounding": ["OSPF uses carrier pigeons to deliver hello packets."]}),
        "自制图引用未定义节点": lambda n: n["sections"][0]["visuals"][0]["spec"]["steps"][0][
            "packets"].append({"from": "R9", "to": "R1", "label": "hello"}),
        "配置块被改写": lambda n: n["sections"][3]["configs"][0].update(
            {"code": "R1#show ip ospf neighbor detail\nNeighbor 9.9.9.9 is FULL"}),
        "结构里出现未定义字段": lambda n: n.update({"my_extra_thoughts": "随便加的字段"}),
        "图内标签未登记就使用": lambda n: n["sections"][0]["figures"][0].update(
            {"labels_seen": [], "explain_zh": "图里 R2 和 R3 通过 192.168.23.0/24 相连。"}),
    }
    for desc, mutate in cases.items():
        bad = json.loads(json.dumps(note))
        mutate(bad)
        out.write_text(json.dumps(bad, ensure_ascii=False, indent=2), encoding="utf-8")
        proc = run(["verify", "--id", pdf_id, *COMMON], expect_rc=1)
        rep = json.loads((BUILD / "reports" / f"{pdf_id}.json").read_text(encoding="utf-8"))
        codes = sorted({e["code"] for e in rep["errors"]})
        check(not rep["passed"], f"拦住「{desc}」(错误码 {codes})")

    print("\n[7/7] 确认源 PDF 未被改动")
    after = pdf.stat().st_mtime, pdf.stat().st_size
    check(before == after, "源 PDF 的修改时间与大小均未变化")

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"❌ {len(FAILURES)} 项失败:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("✅ 全部自测通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
