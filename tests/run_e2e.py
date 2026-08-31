"""端到端自测。

覆盖 6 件事:
  1. 合成 PDF -> 抽取 -> 任务包
  2. PDF 体检(audit)能把扫描件剔除
  3. 章节笔记:注入示例 note.json -> 门禁通过 -> 渲染 Markdown(含必须掌握/难点)
  4. 协议级面试复习笔记:分组 -> 注入 interview.json -> 门禁通过 -> 渲染 Markdown
  5. AI 自动撰写闭环:用本地假 LLM 服务验证"写 -> 被拦 -> 回灌 -> 重写 -> 通过"
  6. 反臆想门禁:19 个必须被拦住的反例;以及源 PDF 未被改动

    python tests/run_e2e.py
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / "tests" / "_tmp"
SRC = TMP / "source"
BUILD = TMP / "build"
NOTES = TMP / "notes"
FIXTURES = ROOT / "tests" / "fixtures"
PY = sys.executable

COMMON = ["--source-root", str(SRC), "--build-dir", str(BUILD), "--notes-dir", str(NOTES)]
FAILURES: list[str] = []


def run(args: list[str], expect_rc: int | None = 0, env: dict | None = None):
    import os
    full_env = {**os.environ, **(env or {})}
    proc = subprocess.run([PY, "-m", "nlnotes", *args], cwd=ROOT,
                          capture_output=True, text=True, env=full_env)
    if expect_rc is not None and proc.returncode != expect_rc:
        FAILURES.append(f"命令 `{' '.join(args[:2])}` 返回码 {proc.returncode},期望 {expect_rc}\n"
                        f"{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}")
    return proc


def check(cond: bool, msg: str) -> None:
    print(f"  {'✅' if cond else '❌'} {msg}")
    if not cond:
        FAILURES.append(msg)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- 1
    print("\n[1/8] 生成合成课程 PDF(正常 + 扫描件 + 网页导出风格深目录)")
    sys.path.insert(0, str(ROOT / "tests"))
    from make_sample_pdf import (build, build_scanned, build_weblike, build_vector,
                                 build_vector_traps)
    pdf = build(SRC)
    scanned = build_scanned(SRC)
    weblike = build_weblike(SRC)
    vector_pdf = build_vector(SRC)
    traps_pdf = build_vector_traps(SRC)
    # 模拟 NetworkLessons 的交叉归档:同一节课出现在多个认证方向下
    dup_dir = SRC / "Cisco" / "CCNA 200-301" / "Unit 4 IP Connectivity" / "4.4 OSPF"
    dup_dir.mkdir(parents=True, exist_ok=True)
    dup_copy = dup_dir / pdf.name
    shutil.copyfile(pdf, dup_copy)
    before = pdf.stat().st_mtime, pdf.stat().st_size

    print("\n[2/8] scan + extract + tasks")
    run(["prepare", *COMMON])
    manifest = load(BUILD / "manifest.json")
    expected = 2 + len(weblike) + 1 + 1 + 1    # 正常+扫描件+网页风格+矢量图+陷阱页+重复副本
    check(manifest["count"] == expected,
          f"扫描到 {expected} 个 PDF(实际 {manifest['count']})")
    check(max(i["depth"] for i in manifest["items"]) >= 5,
          "识别到深层嵌套目录(≥5 层)")

    # --- 重复内容:交叉归档的副本必须被识别并跳过 ---
    dstats = manifest.get("duplicates") or {}
    check(dstats.get("duplicate_files") == 1,
          f"识别出 1 个内容重复的副本(实际 {dstats.get('duplicate_files')})")
    check("title_duplicate_files" in dstats, "同时统计了标题层面的近似重复")
    check("long_path_count" in manifest, "记录了超长路径数量")
    check(dstats.get("unique_files") == expected - 1, "唯一课程数扣掉了副本")
    dup_items = [i for i in manifest["items"] if i.get("dup_of")]
    check(len(dup_items) == 1 and dup_items[0]["dup_of"], "副本正确指向了正本")
    proc = run(["dups", *COMMON])
    check("需要撰写" in proc.stdout and "不要用文件总数" in proc.stdout,
          "dups 给出了实际需撰写的章节数")
    check("标题相同" in proc.stdout, "dups 同时报告标题层面的近似重复")
    check((BUILD / "duplicates.md").exists(), "生成重复内容报告")

    good = next(i for i in manifest["items"]
                if "Neighbor Adjacency" in i["rel_path"] and not i.get("dup_of"))
    bad = next(i for i in manifest["items"] if "Scanned" in i["rel_path"])
    web = next(i for i in manifest["items"] if "Lesson 1.pdf" in i["rel_path"])
    pdf_id = good["id"]

    # --- 网页导出 PDF 的站点导航噪声必须被清掉 ---
    wmeta = load(BUILD / "extract" / web["id"] / "extract.json")
    wtext = (BUILD / "extract" / web["id"] / "text.md").read_text(encoding="utf-8")
    wsecs = load(BUILD / "extract" / web["id"] / "sections.json")["sections"]
    check(wmeta.get("noise_filter", {}).get("dropped_lines", 0) >= 6,
          f"清掉了站点导航噪声(实际 {wmeta.get('noise_filter', {}).get('dropped_lines')} 行)")
    for noise in ("Search …", "Lesson Contents", "«", "Filtering »"):
        check(noise not in wtext, f"原文里已不含噪声「{noise}」")
    check(not any("«" in x["title"] or "»" in x["title"] for x in wsecs),
          "翻页箭头不再被误判成标题")
    check("OSPF supports a number of methods" in wtext, "正文没有被误删")
    check(any("OSPF Filtering Lesson" in x["title"] for x in wsecs), "真正的标题仍被识别")

    # --- 矢量框图(概念课常见):get_images 抽不到,必须靠区域渲染 ---
    vec = next(i for i in manifest["items"] if "AI and ML" in i["rel_path"])
    vfigs = load(BUILD / "extract" / vec["id"] / "figures.json")["figures"]
    check(len(vfigs) >= 2, f"矢量框图被抽出来了(实际 {len(vfigs)} 张)")
    check(all(f["kind"] == "vector" for f in vfigs), "识别为矢量图类型")
    if vfigs:
        # 整张图(含右侧 Output 框)都要在框内 —— 连接线必须把两端合并成一张图
        w = vfigs[0]["bbox"][2] - vfigs[0]["bbox"][0]
        check(w > 250, f"连接线把图两端合并成一整张(宽度 {w:.0f}pt > 250)")

    # --- 矢量误判必须挡掉:页面装饰 与 整页正文 ---
    trap = next(i for i in manifest["items"] if "Data Center Challenges" in i["rel_path"])
    tfigs = load(BUILD / "extract" / trap["id"] / "figures.json")["figures"]
    tpages = {f["page"] for f in tfigs}
    check(1 not in tpages, "页面装饰(搜索框+侧边栏目录)没有被误判成图")
    check(2 not in tpages, "整页正文(外框+项目符号)没有被误判成图")
    check(3 in tpages, "同一份 PDF 里真正的框图仍然抽得到(没有过滤过头)")
    if 3 in tpages:
        real = next(f for f in tfigs if f["page"] == 3)
        rw = real["bbox"][2] - real["bbox"][0]
        check(rw > 300, f"真框图完整(宽度 {rw:.0f}pt)")

    meta = load(BUILD / "extract" / pdf_id / "extract.json")
    check(meta["pages_total"] == 4, f"抽取到 4 页(实际 {meta['pages_total']})")
    check(meta["figure_count"] == 2, f"抽取到 2 张拓扑图(实际 {meta['figure_count']})")
    check(meta["codeblock_count"] >= 1, "识别到 CLI 配置块")
    task = BUILD / "tasks" / pdf_id
    for f in ("TASK.md", "source-text.md", "figures.md", "glossary.md",
              "codeblocks.md", "outline.md", "context.json",
              "note.schema.json", "note.template.json"):
        check((task / f).exists(), f"任务包含 {f}")

    # ---------------------------------------------------------------- 2
    print("\n[3/8] PDF 体检:扫描件必须被剔除")
    run(["audit", *COMMON])
    audit = load(BUILD / "audit.json")
    check(audit["drop"] == 1, f"剔除 1 个不可用 PDF(实际 {audit['drop']})")
    check(bad["id"] in audit["excluded_ids"], "被剔除的正是那份扫描件")
    check(audit["ok"] >= 1, "正常 PDF 判定为可用")
    check((BUILD / "audit.md").exists(), "生成体检报告 audit.md")
    report_md = (BUILD / "audit.md").read_text(encoding="utf-8")
    check("扫描件" in report_md and "OCR" in report_md, "报告给出了扫描件的处理办法")
    # 剔除后,后续阶段应自动跳过
    proc = run(["extract", *COMMON])
    check("已跳过体检剔除" in proc.stdout, "后续阶段自动跳过被剔除的 PDF")

    # ---------------------------------------------------------------- 3
    print("\n[4/8] 章节笔记:注入 note.json -> 门禁 -> 渲染")
    note = json.loads(
        (FIXTURES / "sample-note.json").read_text(encoding="utf-8")
        .replace("__WILL_BE_PATCHED__", pdf_id))
    out = task / "OUTPUT" / "note.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")
    (TMP / "fixture-note.json").write_text(json.dumps(note, ensure_ascii=False, indent=2),
                                           encoding="utf-8")

    run(["build", "--id", pdf_id, *COMMON])
    rep = load(BUILD / "reports" / f"{pdf_id}.json")
    if not rep["passed"]:
        print(json.dumps(rep["errors"], ensure_ascii=False, indent=2)[:3000])
    check(rep["passed"], "示例 note.json 通过门禁")
    check(rep["stats"]["quotes_checked"] == rep["stats"]["quotes_matched"],
          f"全部引用命中原文 ({rep['stats']['quotes_matched']}/{rep['stats']['quotes_checked']})")
    check(rep["stats"]["coverage_ratio"] >= 0.8,
          f"覆盖率 {rep['stats']['coverage_ratio']:.0%} ≥ 80%")
    check(rep["stats"]["points_per_content_page"] >= 2.0,
          f"知识点密度 {rep['stats']['points_per_content_page']} ≥ 2.0(详尽度门槛)")
    check(rep["stats"]["points_with_detail"] >= 4, "有足够多的知识点填了深入说明")

    md = NOTES / good["note_rel_path"]
    check(md.exists(), f"生成章节 Markdown: {md.relative_to(ROOT)}")
    text = md.read_text(encoding="utf-8")
    for needle, desc in [
        ("费曼学习法检验", "含费曼章节"),
        ("必须掌握的关键知识点", "含必须掌握清单"),
        ("本章难点 / Difficulties", "含难点分析"),
        ("为什么容易卡住", "难点写了为什么难"),
        ("怎么突破", "难点写了怎么突破"),
        ("参考答案 / Answers", "含双语答案区"),
        ("fig-p001-1.png", "引用了原文拓扑图"),
        ("v1.gif", "引用了自制动画 GIF"),
        ("v1-steps.png", "引用了分步静态图"),
        ("stateDiagram-v2", "内联了 mermaid(未装 mermaid-cli 时降级)"),
        ("| 判定顺序 |", "渲染了对比表格"),
        ("show ip ospf neighbor", "逐字保留了 CLI 输出"),
        ("面试相关内容", "章节笔记里说明了面试内容在协议级笔记"),
    ]:
        check(needle in text, desc)
    assets = md.parent / "assets" / pdf_id
    gif = assets / "v1.gif"
    check(gif.exists() and gif.stat().st_size > 5000, "动画 GIF 已生成")
    check((assets / "v1-steps.png").exists(), "分步静态图已生成")
    check((assets / "fig-p001-1.png").exists(), "原文配图已复制到 assets")

    # ---------------------------------------------------------------- 4
    print("\n[5/8] 协议级面试复习笔记")
    proc = run(["groups", "--list", "--json", *COMMON])
    groups_info = json.loads(proc.stdout)
    check(all("Route filtering" not in g["key"] for g in groups_info),
          "只有 3 章的深目录被自适应向上合并,没有单独成组")
    check(any(g["chapters"] >= 6 for g in groups_info),
          f"合并后存在 ≥6 章的分组(各组章节数 {[g['chapters'] for g in groups_info]})")
    # 找出 good 这一章所属的分组:路径前缀最长的那个
    cands = [g for g in groups_info if good["rel_path"].startswith(g["key"] + "/")]
    check(bool(cands), f"能定位 {good['rel_path']} 所属的分组")
    mine = max(cands, key=lambda g: len(g["key"]))
    group_id, group_key, group_title = mine["id"], mine["key"], mine["title"]

    run(["groups", *COMMON])
    gdir = BUILD / "groups" / group_id
    for f in ("TASK.md", "chapters.md", "context.json", "interview.schema.json"):
        check((gdir / f).exists(), f"分组任务包含 {f}")
    chapters_md = (gdir / "chapters.md").read_text(encoding="utf-8")
    check(pdf_id in chapters_md, "chapters.md 带上了 pdf_id 供填 grounding")
    check("本章标注的难点" in chapters_md, "chapters.md 汇总了各章难点作为出题素材")

    interview = json.loads(
        (FIXTURES / "sample-interview.json").read_text(encoding="utf-8")
        .replace("__WILL_BE_PATCHED__", pdf_id))
    interview["group_key"] = group_key
    ivp = gdir / "OUTPUT" / "interview.json"
    ivp.parent.mkdir(parents=True, exist_ok=True)
    ivp.write_text(json.dumps(interview, ensure_ascii=False, indent=2), encoding="utf-8")

    run(["build-group", "--group", group_id, *COMMON])
    grep_ = load(BUILD / "reports" / f"group-{group_id}.json")
    if not grep_["passed"]:
        print(json.dumps(grep_["errors"], ensure_ascii=False, indent=2)[:3000])
    check(grep_["passed"], "示例 interview.json 通过门禁")
    check(grep_["stats"]["grounding_checked"] == grep_["stats"]["grounding_matched"],
          f"全部 grounding 命中原文 "
          f"({grep_['stats']['grounding_matched']}/{grep_['stats']['grounding_checked']})")

    imd = NOTES / group_key / f"00-面试复习-{group_title}.md"
    check(imd.exists(), f"生成面试复习 Markdown: {imd.relative_to(ROOT)}")
    itext = imd.read_text(encoding="utf-8")
    for needle, desc in [
        ("知识体系图 / Knowledge Map", "含知识体系图"),
        ("必须掌握清单 / Must Master", "含跨章必须掌握"),
        ("高频必考基础 / 原理题", "含高频原理题"),
        ("高分答题模板", "含高分答题模板"),
        ("得分要点 / Scoring points", "含得分要点"),
        ("场景化面试题 / Scenario", "含场景化面试题"),
        ("解题框架", "场景题含解题框架"),
        ("面试官连环追问", "含连环追问"),
        ("第 1 层追问(是什么)", "追问第 1 层"),
        ("第 2 层追问(为什么 / 怎么做)", "追问第 2 层"),
        ("第 3 层追问(边界与代价)", "追问第 3 层"),
        ("面试官想验证", "追问写了考察意图"),
        ("避坑指南 / Common Pitfalls", "含避坑指南"),
        ("很多人会这样说", "避坑写了候选人原话"),
        ("课程外扩展", "发散内容被单独标注"),
        ("🇬🇧", "题目与答案中英双语"),
        ("ospf-neighbor-adjacency.md", "可跳回对应章节笔记"),
    ]:
        check(needle in itext, desc)

    # ---------------------------------------------------------------- 5
    print("\n[6/8] AI 自动撰写闭环(本地假 LLM,不花钱)")
    port = free_port()
    server = subprocess.Popen(
        [PY, str(ROOT / "tests" / "mock_llm_server.py"), str(port),
         str(TMP / "fixture-note.json"), "broken"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.5)
        out.unlink(missing_ok=True)
        proc = run(["write", "--id", pdf_id, *COMMON], env={
            "NLNOTES_API_KEY": "dummy",
            "NLNOTES_WRITER_BASE_URL": f"http://127.0.0.1:{port}/v1",
            "NLNOTES_WRITER_MODEL": "mock",
        })
        check("第 1 轮" in proc.stdout and "第 2 轮" in proc.stdout,
              "第 1 轮被门禁拦下,自动进入第 2 轮")
        check("✅ 通过" in proc.stdout, "回灌错误后第 2 轮通过")
        check(out.exists(), "自动写出了 note.json")
        final = load(BUILD / "reports" / f"{pdf_id}.json")
        check(final["passed"], "自动撰写的结果通过门禁")
        check((BUILD / "write-log.jsonl").exists(), "记录了 token 用量账本")
        proc = run(["cost", *COMMON])
        check("费用" in proc.stdout, "cost 能汇总费用")
    finally:
        server.terminate()
        server.wait(timeout=10)

    proc = run(["write", "--dry-run", "--force", "--id", pdf_id, *COMMON])
    check("成本预估" in proc.stdout, "--dry-run 只预估不发请求")

    run(["diag", *COMMON])
    diag_md = BUILD / "diagnosis.md"
    check(diag_md.exists(), "生成诊断报告 build/diagnosis.md")
    dtext = diag_md.read_text(encoding="utf-8")
    for needle, desc in [
        ("关键抽取参数", "诊断报告含当前抽取参数"),
        ("课程目录概况", "诊断报告含目录概况"),
        ("PDF 体检", "诊断报告含体检汇总"),
        ("抽取质量", "诊断报告含抽取质量统计"),
        ("抽出的图片清单", "诊断报告含抽样图片清单"),
        ("原文文本层样例", "诊断报告含原文文本样例"),
    ]:
        check(needle in dtext, desc)

    # ---------------------------------------------------------------- 6
    print("\n[7/8] 反臆想门禁:必须拦住的反例")
    note["pdf_id"] = pdf_id
    chapter_cases = {
        "编造的定时器数值": lambda n: n["sections"][0]["points"][3].update(
            {"text_zh": "dead interval 默认是 120 秒,是 hello interval 的四倍。"}),
        "编造的协议名": lambda n: n["sections"][0]["points"][0].update(
            {"text_zh": "OSPF 路由器靠 hello 报文发现邻居,这一点和 FooBarProtocol 一样。"}),
        "深入说明里夹带臆想": lambda n: n["sections"][0]["points"][0].update(
            {"detail_zh": "补充一点:实际上还会用到 QuuxTimer 这个定时器。"}),
        "引用不是原文": lambda n: n["sections"][0]["points"][0].update(
            {"text_en_quote": "OSPF routers exchange gossip messages to find their friends."}),
        "页码写错": lambda n: n["sections"][0]["points"][0].update({"page": 3}),
        "不存在的图": lambda n: n["sections"][0]["figures"][0].update({"figure_id": "fig-p099-1"}),
        "发散措辞": lambda n: n.update({"summary_zh": n["summary_zh"] + " 笔者认为这在生产环境很重要。"}),
        "题目数量不足": lambda n: n["feynman"].update({"questions": n["feynman"]["questions"][:3]}),
        "英文答案混入中文": lambda n: n["feynman"]["questions"][0].update(
            {"answer_en": "They use hello 报文 to discover neighbors on a link."}),
        "覆盖度不足": lambda n: n.update({"sections": n["sections"][:1]}),
        "知识点密度过低(空洞概括)": lambda n: [
            s.update({"points": s["points"][:1]}) for s in n["sections"]],
        "必须掌握缺原文依据": lambda n: n["feynman"]["must_master"][0].update(
            {"evidence_quote": "OSPF neighbors always match everything automatically."}),
        "难点分析缺原文依据": lambda n: n["feynman"]["difficulties"][0].update(
            {"evidence_quote": "The 2-Way state is reached after three hello packets."}),
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
    for desc, mutate in chapter_cases.items():
        badn = json.loads(json.dumps(note))
        mutate(badn)
        out.write_text(json.dumps(badn, ensure_ascii=False, indent=2), encoding="utf-8")
        run(["verify", "--id", pdf_id, *COMMON], expect_rc=1)
        r = load(BUILD / "reports" / f"{pdf_id}.json")
        codes = sorted({e["code"] for e in r["errors"]})
        check(not r["passed"], f"章节笔记拦住「{desc}」(错误码 {codes})")

    # 恢复正确的章节笔记,再测面试笔记的反例
    out.write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")
    run(["verify", "--id", pdf_id, *COMMON])

    interview_cases = {
        "grounding 引用不是原文": lambda v: v["fundamentals"][0]["grounding"][0].update(
            {"quote": "OSPF elects three designated routers on every network."}),
        "grounding 页码写错": lambda v: v["fundamentals"][0]["grounding"][0].update({"page": 4}),
        "核心答案夹带课程外内容": lambda v: v["fundamentals"][0]["answer_template_zh"].update(
            {"closing": "另外还要考虑 QuuxProtocol 的兼容性问题。"}),
        "英文答案混入中文": lambda v: v["followups"][0]["layers"][0].update(
            {"answer_en": "The order is Down, Init, 2-Way and Full 状态。"}),
        "连环追问不是三层": lambda v: v["followups"][0].update(
            {"layers": v["followups"][0]["layers"][:2]}),
        "避坑条目数量不足": lambda v: v.update({"pitfalls": v["pitfalls"][:2]}),
        "场景题数量不足": lambda v: v.update({"scenarios": v["scenarios"][:1]}),
        "引用了未覆盖的章节": lambda v: v["fundamentals"][0]["grounding"][0].update(
            {"pdf_id": "some-other-chapter-000"}),
        "出现不确定表述": lambda v: v["pitfalls"][0].update(
            {"why_wrong_zh": "我猜这里应该是记错了,大概是把两个状态搞混了吧,具体原因不太确定。"}),
        "group_key 与实际分组不一致": lambda v: v.update({"group_key": "Made/Up/Group"}),
    }
    for desc, mutate in interview_cases.items():
        badv = json.loads(json.dumps(interview))
        mutate(badv)
        ivp.write_text(json.dumps(badv, ensure_ascii=False, indent=2), encoding="utf-8")
        run(["build-group", "--group", group_id, *COMMON], expect_rc=1)
        r = load(BUILD / "reports" / f"group-{group_id}.json")
        codes = sorted({e["code"] for e in r["errors"]})
        check(not r["passed"], f"面试笔记拦住「{desc}」(错误码 {codes})")

    # ---------------------------------------------------------------- 7
    proc = run(["stats", *COMMON])
    check("知识点密度" in proc.stdout and "引用校验通过率" in proc.stdout,
          "stats 汇总质量指标(可用于对比不同模型)")

    print("\n[7.25/8] 配置升级:补齐新增项、保留自定义值")
    up_cfg = TMP / "old-style-config.json"
    base_up = json.loads((ROOT / "config" / "pipeline.example.json")
                         .read_text(encoding="utf-8"))
    removed = ["group_mode", "selection_file", "tesseract_cmd"]
    for k in removed:
        base_up.pop(k, None)
    base_up["obsolete_key_from_old_version"] = 123
    base_up.update({"source_root": str(SRC), "build_dir": str(BUILD),
                    "notes_dir": str(NOTES), "figure_ocr": True})
    # init --upgrade 只认默认路径 config/pipeline.json,所以临时接管它
    real_cfg = ROOT / "config" / "pipeline.json"
    real_backup = real_cfg.read_text(encoding="utf-8") if real_cfg.exists() else None
    try:
        real_cfg.write_text(json.dumps(base_up, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        proc = run(["init"])
        check("少 3 个配置项" in proc.stdout, "init 能发现配置比当前版本旧")
        check("init --upgrade" in proc.stdout, "并给出补齐命令")
        proc = run(["doctor"], expect_rc=None)
        check("init --upgrade" in proc.stdout, "doctor 也提示配置过期")
        check("撰写模型" in proc.stdout, "doctor 显示撰写模型与 Key 状态")
        proc = run(["init", "--upgrade"])
        check("补齐了 3 个新增配置项" in proc.stdout, "补齐了缺少的新增项")
        check("移除了 1 个已废弃的项" in proc.stdout, "移除了已废弃的项")
        upgraded = json.loads(real_cfg.read_text(encoding="utf-8"))
        check(all(k in upgraded for k in removed), "新增项都补上了")
        check(upgraded["figure_ocr"] is True and upgraded["source_root"] == str(SRC),
              "原先改过的值被保留")
        check("obsolete_key_from_old_version" not in upgraded, "废弃项被清掉")
        check((ROOT / "config" / "pipeline.json.bak").exists(), "升级前自动备份")
        proc = run(["init"])
        check("配置已是最新" in proc.stdout, "升级后 init 报告已是最新")
    finally:
        (ROOT / "config" / "pipeline.json.bak").unlink(missing_ok=True)
        if real_backup is None:
            real_cfg.unlink(missing_ok=True)
        else:
            real_cfg.write_text(real_backup, encoding="utf-8")

    print("\n[7.3/8] 图内文字 OCR(装了 tesseract 才测)")
    import shutil as _sh
    if not _sh.which("tesseract"):
        print("  ➖ 未安装 tesseract,跳过 OCR 相关检查")
    else:
        ocr_cfg = TMP / "ocr-config.json"
        base = json.loads((ROOT / "config" / "pipeline.example.json")
                          .read_text(encoding="utf-8"))
        base.update({"figure_ocr": True, "source_root": str(SRC),
                     "build_dir": str(BUILD), "notes_dir": str(NOTES)})
        ocr_cfg.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
        oc = ["--config", str(ocr_cfg)]
        proc = run(["doctor", *oc])
        check("图内文字 OCR : ✅ 可用" in proc.stdout,
              "doctor 能自动定位 tesseract 并报告 OCR 可用")
        run(["extract", "--id", pdf_id, "--force", *oc])
        ofigs = load(BUILD / "extract" / pdf_id / "figures.json")["figures"]
        check(any((f.get("ocr_text") or "").strip() for f in ofigs),
              "OCR 抽出了图内文字")
        # OCR 对小字号不可靠,标签对不上只能是警告,不能把正例卡死
        proc = run(["verify", "--id", pdf_id, "--show", *oc])
        orep = load(BUILD / "reports" / f"{pdf_id}.json")
        check(orep["passed"], "开启 OCR 后正例仍然通过(标签对不上只降级为警告)")
        codes = {e["code"] for e in orep["errors"]}
        check("G010" not in codes, "OCR 标签不匹配不会变成硬错误")
        # 恢复不带 OCR 的抽取产物,避免影响后续步骤
        run(["extract", "--id", pdf_id, "--force", *COMMON])
        run(["verify", "--id", pdf_id, *COMMON])

    print("\n[7.4/8] 选课清单:只做指定方向")
    sel = ROOT / "config" / "selection.txt"
    sel_backup = sel.read_text(encoding="utf-8") if sel.exists() else None
    try:
        sel.parent.mkdir(parents=True, exist_ok=True)
        sel.write_text("# e2e 测试清单\nCisco/CCIE Enterprise\n!*Lesson 7*\n",
                       encoding="utf-8")
        proc = run(["select", *COMMON])
        check("清单命中" in proc.stdout, "select --list 能预览命中情况")
        check("每条规则各自命中多少" in proc.stdout, "预览列出每条规则的命中数")
        import re as _re
        m = _re.search(r"清单命中:\*\*(\d+)\*\*", proc.stdout)
        hit = int(m.group(1)) if m else -1
        check(0 < hit < manifest["count"], f"清单确实缩小了范围(命中 {hit}/{manifest['count']})")
        proc = run(["extract", *COMMON])
        check("选课清单生效" in proc.stdout, "其他命令自动遵守选课清单")
        check("Lesson 7" not in proc.stdout, "排除规则生效")
        proc = run(["select", "--init", "--force", *COMMON])
        check("已生成清单模板" in proc.stdout or sel.exists(), "select --init 能按课程库生成模板")

        # 前缀匹配语义:Routing 不应命中 "Unit 2 Routing" 这类深层目录
        sel.write_text("# 前缀匹配测试\n===== 装饰行不应被当成规则 =====\nRouting\n",
                       encoding="utf-8")
        proc = run(["select", *COMMON])
        check("装饰行" not in proc.stdout.split("每条规则")[-1],
              "`===== xxx =====` 装饰行被忽略,没当成规则")
        import re as _re2
        m2 = _re2.search(r"清单命中:\*\*(\d+)\*\*", proc.stdout)
        check(m2 and int(m2.group(1)) == 0,
              f"不含通配符时按前缀匹配:`Routing` 不会误命中深层的 Unit 2 Routing"
              f"(命中 {m2.group(1) if m2 else '?'})")
        check("命中 0 个" in proc.stdout, "对命中 0 个的规则给出告警")

        # 想匹配任意层级要显式写通配符
        sel.write_text("*Routing*\n", encoding="utf-8")
        proc = run(["select", *COMMON])
        m3 = _re2.search(r"清单命中:\*\*(\d+)\*\*", proc.stdout)
        check(m3 and int(m3.group(1)) > 0, "写成 `*Routing*` 才匹配任意层级")

        # group_mode=selection:一条包含规则出一份面试复习笔记
        sel.write_text("*1.2.a OSPF basics*\n*1.3 Switching*\n", encoding="utf-8")
        sel_cfg = TMP / "selection-group-config.json"
        base2 = json.loads((ROOT / "config" / "pipeline.example.json")
                           .read_text(encoding="utf-8"))
        base2.update({"group_mode": "selection", "source_root": str(SRC),
                      "build_dir": str(BUILD), "notes_dir": str(NOTES)})
        sel_cfg.write_text(json.dumps(base2, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        proc = run(["groups", "--list", "--json", "--config", str(sel_cfg)])
        ginfo = json.loads(proc.stdout)
        check(len(ginfo) == 2,
              f"group_mode=selection 时每条规则各成一组(实际 {len(ginfo)} 组)")
        check(all(g["chapters"] > 0 for g in ginfo), "每组都有章节")
        # 同样的清单换成 auto 会因为章节太少而合并
        base2["group_mode"] = "auto"
        sel_cfg.write_text(json.dumps(base2, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        proc = run(["groups", "--list", "--json", "--config", str(sel_cfg)])
        check(len(json.loads(proc.stdout)) < 2,
              "auto 模式下同样的清单会被合并(印证两种模式的差别)")
    finally:
        if sel_backup is None:
            sel.unlink(missing_ok=True)
        else:
            sel.write_text(sel_backup, encoding="utf-8")
    # 清单撤销后重新抽取,保证后续步骤数据完整
    run(["extract", *COMMON])

    print("\n[7.5/8] 副本笔记指向正本")
    run(["dups", "--write-pointers", *COMMON])
    dup_md = NOTES / dup_items[0]["note_rel_path"]
    check(dup_md.exists(), "为副本生成了占位笔记,目录树没有空洞")
    if dup_md.exists():
        dtext = dup_md.read_text(encoding="utf-8")
        check("内容完全相同" in dtext, "占位笔记说明了这是重复内容")
        check("duplicate-pointer" in dtext, "占位笔记标注了类型")

    print("\n[8/8] 确认源 PDF 未被改动")
    after = pdf.stat().st_mtime, pdf.stat().st_size
    check(before == after, "源 PDF 的修改时间与大小均未变化")
    check(scanned.exists(), "被剔除的 PDF 仍然原样保留在源目录")

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
