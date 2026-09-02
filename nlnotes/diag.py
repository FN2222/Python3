"""诊断打包 —— 把"调参需要看的信息"汇总成一个文件,方便贴给别人看。

    python -m nlnotes diag

产出 build/diagnosis.md,内容包括:
  * 环境:路径、依赖、中文字体、可选工具
  * 课程目录概况:PDF 总数、一级方向、目录深度分布
  * PDF 体检汇总(若已跑过 audit)
  * 抽样若干个 PDF 的抽取质量:页数、每页字符、图片数量与类型、代码块数、标题来源
  * 一份完整的 figures.md(判断拓扑图抽得对不对)
  * 一段原文文本(判断文本层提取质量)

这个文件不含任何课程正文的大段内容,只有统计与少量样本,可以放心分享。
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from nlnotes import __version__
from nlnotes.config import Config
from nlnotes.util import log, read_json, write_text


def _env_section(cfg: Config) -> list[str]:
    from nlnotes.visuals import find_font
    lines = ["## 一、环境", "",
             f"- nlnotes 版本:{__version__}",
             f"- 配置文件:`{cfg.path or '(内置默认值)'}`",
             f"- 课程根目录:`{cfg.source_root}` — "
             f"{'✅ 存在' if cfg.source_root.exists() else '❌ 不存在'}",
             f"- 中间产物目录:`{cfg.build_dir}`",
             f"- 笔记输出目录:`{cfg.notes_dir}`", ""]

    lines += ["**依赖**", ""]
    for mod, why in (("pymupdf", "PDF 抽取"), ("PIL", "动画/静态图"),
                     ("jinja2", "Markdown 渲染"), ("rapidfuzz", "原文比对"),
                     ("jsonschema", "结构校验"), ("requests", "调用模型 API(可选)")):
        try:
            __import__(mod)
            lines.append(f"- ✅ {mod} — {why}")
        except ImportError:
            lines.append(f"- ❌ {mod} — {why}")
    lines.append("")

    lines += ["**可选外部工具**(缺失会自动降级)", ""]
    for exe, why in ((str(cfg["mermaid_cli"]), "mermaid 渲染成 PNG"),
                     (str(cfg["dot_cmd"]), "graphviz 渲染成 PNG"),
                     (str(cfg["ffmpeg_cmd"]), "额外输出 MP4")):
        lines.append(f"- {'✅' if shutil.which(exe) else '➖'} {exe} — {why}")
    try:
        import pytesseract  # noqa: F401
        ocr_pkg = True
    except ImportError:
        ocr_pkg = False
    from nlnotes.extract import ocr_status
    st = ocr_status(cfg)
    if not st["enabled"]:
        lines.append("- ➖ 图内文字 OCR — 未启用(config 的 figure_ocr = false)")
    elif st["available"]:
        lines.append(f"- ✅ 图内文字 OCR — 可用:`{st['cmd']}`")
    else:
        lines.append(f"- ❌ 图内文字 OCR — **已开启但不可用**:{st['reason']}")
    lines.append(f"- {'✅' if ocr_pkg else '➖'} pytesseract 包"
                 f"(PATH 里的 tesseract:{'找到' if shutil.which('tesseract') else '未找到'})")
    lines.append("")

    font = find_font(cfg)
    lines += [f"**中文字体**:{font or '❌ 未找到 —— 自制图里的中文会变方块'}", "",
              "**关键抽取参数(当前值)**", "",
              "| 参数 | 当前值 | 作用 |", "| --- | --- | --- |"]
    for key, why in (("figure_min_width", "位图最小宽度,小于此值丢弃"),
                     ("figure_min_height", "位图最小高度"),
                     ("figure_min_area", "位图最小面积"),
                     ("extract_vector_figures", "是否渲染矢量拓扑图区域"),
                     ("vector_min_drawings", "一页矢量对象数达到该值才尝试区域渲染"),
                     ("vector_min_cluster_area", "矢量图区域最小面积"),
                     ("figure_ocr", "是否 OCR 图内文字"),
                     ("min_points_per_content_page", "知识点密度门槛"),
                     ("coverage_min_ratio", "正文覆盖率门槛")):
        lines.append(f"| `{key}` | `{cfg[key]}` | {why} |")
    lines.append("")
    return lines


def _manifest_section(cfg: Config) -> tuple[list[str], list[dict[str, Any]]]:
    if not cfg.manifest_path.exists():
        return ["## 二、课程目录概况", "",
                "> ⚠️ 还没跑过 `nlnotes scan`,无法统计。", ""], []
    m = read_json(cfg.manifest_path)
    items = m["items"]
    from collections import Counter
    by_cat = Counter(it["course_path"][0] if it["course_path"] else "(根目录)" for it in items)
    by_depth = Counter(it["depth"] for it in items)

    lines = ["## 二、课程目录概况", "",
             f"- PDF 总数:**{len(items)}**",
             f"- 一级方向数:{len(by_cat)}",
             f"- 目录深度分布:" + "、".join(f"{d} 层 × {n}" for d, n in sorted(by_depth.items())),
             "", "**各一级方向的 PDF 数量**", "",
             "| 一级方向 | PDF 数 |", "| --- | --- |"]
    for cat, n in by_cat.most_common():
        lines.append(f"| {cat} | {n} |")
    dup = m.get("duplicates") or {}
    if dup:
        total = len(items)
        dupf = dup.get("duplicate_files", 0)
        lines += ["", "**重复内容**(同一节课被交叉归档到多个认证方向)", "",
                  f"- 内容互不相同的课程数:**{dup.get('unique_files', total)}**",
                  f"- 重复副本数:**{dupf}**"
                  + (f"({dupf / total:.0%})" if total else ""),
                  f"- 重复组数:{dup.get('duplicate_groups', 0)}"]
        if dupf:
            lines.append(f"- ⚠️ **实际需要撰写的章节数是 "
                         f"{dup.get('unique_files', total)},而不是 {total}** —— "
                         f"按这个数估成本。副本会自动跳过,并生成指向正本的短笔记。")
            top = dup.get("largest_groups") or []
            if top:
                lines += ["", "重复最多的几组:", ""]
                for g in top[:5]:
                    lines.append(f"  - {g['count']} 份 — `{g['canonical']}`")
        lines.append("")

    lines += ["", "**目录层级样例(前 8 个)**", "", "```"]
    for it in items[:8]:
        lines.append(it["rel_path"])
    lines += ["```", ""]
    return lines, items


def _groups_section(cfg: Config) -> list[str]:
    """分组预览 —— 面试复习笔记按什么粒度切,直接影响素材是否够用。"""
    if not cfg.manifest_path.exists():
        return []
    try:
        from nlnotes.groups import discover_groups
        groups = discover_groups(cfg)
    except Exception as exc:
        return ["## 二点五、面试复习笔记的分组预览", "",
                f"> 无法计算分组:{exc}", ""]

    sizes = sorted((len(g["items"]) for g in groups.values()), reverse=True)
    mode = cfg.get("group_mode", "auto")
    lines = ["## 二点五、面试复习笔记的分组预览", "",
             f"- 分组方式:`{mode}`"
             + (f",每组至少 {cfg['group_min_chapters']} 章" if mode == "auto" else
                f",按第 {cfg['group_depth']} 层目录"),
             f"- 分组数:**{len(groups)}**(也就是最终会产出多少份面试复习笔记)",
             f"- 每组章节数:最小 {sizes[-1] if sizes else 0} / "
             f"中位 {sizes[len(sizes) // 2] if sizes else 0} / 最大 {sizes[0] if sizes else 0}",
             ""]
    small = [g for g in groups.values() if len(g["items"]) < 4]
    if small:
        lines.append(f"- ⚠️ 有 {len(small)} 组不足 4 章 —— 这些组的面试题素材偏少,"
                     f"可以考虑调大 `group_min_chapters`")
    big = [g for g in groups.values() if len(g["items"]) > 40]
    if big:
        lines.append(f"- ⚠️ 有 {len(big)} 组超过 40 章 —— 复习笔记会很长,"
                     f"可以考虑调小 `group_min_chapters`,或改用 `group_mode: depth`")
    lines += ["", "**章节数最多的 20 个分组**", "",
              "| 分组(协议 / 方向) | 章节数 |", "| --- | --- |"]
    for g in sorted(groups.values(), key=lambda x: -len(x["items"]))[:20]:
        lines.append(f"| `{g['key']}` | {len(g['items'])} |")
    lines.append("")
    return lines


def _audit_section(cfg: Config) -> list[str]:
    p = cfg.build_dir / "audit.json"
    if not p.exists():
        return ["## 三、PDF 体检", "",
                "> ⚠️ 还没跑过 `nlnotes audit`。建议先跑,它会把扫描件之类不可用的 PDF 剔除。",
                ""]
    a = read_json(p)
    lines = ["## 三、PDF 体检", "",
             f"- ✅ 可用:**{a['ok']}**",
             f"- ⚠️ 需注意:**{a['warn']}**",
             f"- ❌ 剔除:**{a['drop']}**", ""]

    drops = [r for r in a["items"] if r["verdict"] == "drop"]
    if drops:
        lines += [f"**被剔除的 {len(drops)} 个(最多列 20 个)**", "",
                  "| 文件 | 页数 | 每页字符 | 原因 |", "| --- | --- | --- | --- |"]
        for r in drops[:20]:
            lines.append(f"| `{r['rel_path']}` | {r['pages']} | {r['chars_per_page']} | "
                         f"{'；'.join(r['reasons'])} |")
        lines.append("")

    warns = [r for r in a["items"] if r["verdict"] == "warn"]
    if warns:
        lines += [f"**需注意的 {len(warns)} 个(最多列 20 个)**", "",
                  "| 文件 | 页数 | 每页字符 | 内嵌图 | 提示 |", "| --- | --- | --- | --- | --- |"]
        for r in warns[:20]:
            lines.append(f"| `{r['rel_path']}` | {r['pages']} | {r['chars_per_page']} | "
                         f"{r['images']} | {'；'.join(r['reasons'])} |")
        lines.append("")

    oks = [r for r in a["items"] if r["verdict"] == "ok"]
    if oks:
        cpp = [r["chars_per_page"] for r in oks]
        img = [r["images"] for r in oks]
        lines += ["**可用文件的分布**(用来判断抽取参数是否合适)", "",
                  f"- 每页字符数:最小 {min(cpp)} / 中位 {sorted(cpp)[len(cpp)//2]} / 最大 {max(cpp)}",
                  f"- 内嵌位图数:最小 {min(img)} / 中位 {sorted(img)[len(img)//2]} / 最大 {max(img)}",
                  ""]
    return lines


def _extract_section(cfg: Config, items: list[dict[str, Any]],
                     sample: int) -> tuple[list[str], list[dict[str, Any]]]:
    done = []
    for it in items:
        p = cfg.extract_dir(it["id"]) / "extract.json"
        if p.exists():
            try:
                done.append((it, read_json(p)))
            except Exception:
                pass
    if not done:
        return (["## 四、抽取质量", "",
                 "> ⚠️ 还没跑过 `nlnotes extract` / `prepare`,无法评估抽取质量。", ""], [])

    lines = ["## 四、抽取质量", "",
             f"已抽取 **{len(done)}** 个 PDF。下表是全部已抽取文件的统计:", "",
             "| 文件 | 页数 | 正文页 | 位图 | 矢量图 | 代码块 | 标题来源 | 清掉的噪声行 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for it, meta in done[:40]:
        figs = read_json(cfg.extract_dir(it["id"]) / "figures.json", {"figures": []})["figures"]
        raster = sum(1 for f in figs if f.get("kind") == "raster")
        vector = sum(1 for f in figs if f.get("kind") == "vector")
        secs = read_json(cfg.extract_dir(it["id"]) / "sections.json", {"sections": []})["sections"]
        src = secs[0].get("source", "-") if secs else "未识别"
        nf = meta.get("noise_filter") or {}
        noise_cell = str(nf.get("dropped_lines", "-")) if nf.get("enabled") else "未启用"
        lines.append(f"| `{Path(it['rel_path']).name}` | {meta.get('pages_total')} | "
                     f"{len(meta.get('content_pages', []))} | {raster} | {vector} | "
                     f"{meta.get('codeblock_count')} | {'PDF 书签' if src == 'toc' else src} | "
                     f"{noise_cell} |")
    if len(done) > 40:
        lines.append(f"| ...(还有 {len(done) - 40} 个) | | | | | | |")
    lines.append("")

    total_figs = 0
    no_fig = []
    for it, meta in done:
        n = meta.get("figure_count", 0)
        total_figs += n
        if n == 0:
            no_fig.append(it["rel_path"])
    lines += [f"- 累计抽出图片:**{total_figs}** 张,平均每个 PDF "
              f"{total_figs / max(1, len(done)):.1f} 张", ""]
    if no_fig:
        lines += [f"- ⚠️ **有 {len(no_fig)} 个 PDF 一张图都没抽到**(最多列 15 个):", ""]
        for r in no_fig[:15]:
            lines.append(f"  - `{r}`")
        lines += ["", "  → 若这些章节原文确实有拓扑图,说明抽取参数需要调:"
                  "位图被尺寸过滤掉了(调小 `figure_min_*`),"
                  "或者图是矢量绘制的(调小 `vector_min_drawings`)。", ""]
    return lines, done


def _samples_section(cfg: Config, done: list[tuple], sample: int) -> list[str]:
    if not done:
        return []
    lines = ["## 五、抽样细节", "",
             f"下面抽 {min(sample, len(done))} 个 PDF 展示细节,用来判断抽得对不对。", ""]
    for it, meta in done[:sample]:
        d = cfg.extract_dir(it["id"])
        lines += [f"### `{it['rel_path']}`", "",
                  f"- pdf_id:`{it['id']}`",
                  f"- 页数 {meta.get('pages_total')},正文页 "
                  f"{len(meta.get('content_pages', []))},图 {meta.get('figure_count')} 张,"
                  f"代码块 {meta.get('codeblock_count')} 段", ""]

        figs = read_json(d / "figures.json", {"figures": []})["figures"]
        if figs:
            lines += ["**抽出的图片清单**", "",
                      "| figure_id | 页 | 类型 | 尺寸 | 推测图注 | OCR 识别到的文字 |",
                      "| --- | --- | --- | --- | --- | --- |"]
            for f in figs[:25]:
                ocr = (f.get("ocr_text") or "").strip()
                lines.append(f"| `{f['figure_id']}` | {f['page']} | {f['kind']} | "
                             f"{f['width']}x{f['height']} | "
                             f"{(f.get('caption_guess') or '-')[:45]} | "
                             f"{(ocr[:60] + '…') if len(ocr) > 60 else (ocr or '(未开启 OCR)')} |")
            lines.append("")
        else:
            lines += ["**没有抽到任何图片。** 请打开原 PDF 确认:是本来就没有图,还是被过滤掉了。", ""]

        nf = meta.get("noise_filter") or {}
        if nf.get("enabled") and nf.get("samples"):
            lines += [f"**被清掉的站点导航噪声**(共 {nf.get('dropped_lines', 0)} 行,"
                      f"下面是去重后的样例 —— 请确认没有误删正文)", "", "```"]
            lines += [str(x) for x in nf["samples"]]
            lines += ["```", ""]

        secs = read_json(d / "sections.json", {"sections": []})["sections"]
        if secs:
            lines += ["**识别到的标题层级(前 15 条)**", "", "```"]
            for s in secs[:15]:
                indent = "  " * (int(s.get("level", 1)) - 1)
                lines.append(f"{indent}- (p.{s['page']}) {s['title']}")
            lines += ["```", ""]
        else:
            lines += ["**没有识别到标题层级。** 小节需要 AI 自行按段落划分。", ""]

        text_path = d / "text.md"
        if text_path.exists():
            body = text_path.read_text(encoding="utf-8").splitlines()
            head = body[7:47]         # 跳过文件头,取前几十行正文
            lines += ["**原文文本层样例(用来判断提取质量,是否有乱码/断词)**", "", "```text"]
            lines += head
            lines += ["```", ""]

        cbs = read_json(d / "codeblocks.json", {"codeblocks": []})["codeblocks"]
        if cbs:
            lines += ["**识别到的第一段配置/命令块**", "", "```text",
                      cbs[0]["code"][:800], "```", ""]
    return lines


def diagnose(cfg: Config, sample: int = 3) -> Path:
    lines = ["# nlnotes 诊断报告", "",
             "把这份文件发给协助你调参的人,或直接对照它自查。",
             "内容只有统计与少量样本,不含课程正文大段内容。", ""]
    lines += _env_section(cfg)
    man_lines, items = _manifest_section(cfg)
    lines += man_lines
    lines += _groups_section(cfg)
    lines += _audit_section(cfg)
    ex_lines, done = _extract_section(cfg, items, sample)
    lines += ex_lines
    lines += _samples_section(cfg, done, sample)

    lines += ["## 六、接下来该做什么", "",
              "对照上面的信息判断:", "",
              "1. **图抽得对吗?** 打开原 PDF 看几页,和「抽出的图片清单」比对。"
              "抽多了(把图标当图)就调大 `figure_min_area`;抽少了就调小 `figure_min_*` "
              "或 `vector_min_drawings`。改完跑 `nlnotes extract --force`。",
              "2. **文本层干净吗?** 看「原文文本层样例」有没有乱码、断词、行序错乱。"
              "乱码严重的文件应该在体检里被剔除;个别断词属正常。",
              "3. **标题识别对吗?** 若大量文件「未识别」,笔记的小节划分会更依赖 AI 判断,"
              "不影响门禁,但可以接受。",
              "4. **体检剔除的文件怎么处理?** 扫描件先 OCR 成可搜索 PDF 再放回原目录。",
              "5. **噪声清掉的对吗?** 看「被清掉的站点导航噪声」样例,"
              "如果误删了正文,把对应的词从 config 的 `text_noise_lines` 里去掉。",
              "6. **分组粒度合适吗?** 看第二点五节。分组数就是最终面试复习笔记的份数;"
              "每组章节数太少就调大 `group_min_chapters`,太多就调小。", ""]

    out = cfg.build_dir / "diagnosis.md"
    write_text(out, "\n".join(lines))
    log(f"诊断报告已生成: {out}", "ok")
    return out
