"""生成一份用于自测的"假课程" PDF(模仿 NetworkLessons 的排版:正文 + 拓扑图 + CLI 输出)。

仅用于验证流水线,不涉及任何真实课程内容。
    python tests/make_sample_pdf.py tests/_tmp/source
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

W, H = A4


def _topology(path: Path, labels: list[str], title: str) -> None:
    img = Image.new("RGB", (900, 380), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 14), title, fill=(20, 40, 70))
    xs = [140, 450, 760]
    for x, name in zip(xs, labels):
        d.ellipse([x - 52, 150, x + 52, 254], outline=(40, 80, 140), width=5)
        d.text((x - 14, 196), name, fill=(20, 40, 70))
    for a, b in zip(xs, xs[1:]):
        d.line([(a + 54, 202), (b - 54, 202)], fill=(90, 110, 140), width=5)
    d.text((250, 168), "192.168.12.0/24", fill=(90, 110, 140))
    d.text((560, 168), "192.168.23.0/24", fill=(90, 110, 140))
    img.save(path)


PAGES = [
    ("Introduction to OSPF Neighbor Adjacency", [
        "OSPF routers use hello packets to discover neighbors on a link.",
        "The hello packet is sent to multicast address 224.0.0.5 every 10 seconds",
        "on a broadcast network segment.",
        "Two routers become neighbors only when the hello interval, the dead interval,",
        "the area ID and the subnet mask all match.",
        "The dead interval is 40 seconds by default, which is four times the hello interval.",
    ], "fig1"),
    ("Neighbor States", [
        "An OSPF neighbor moves through several states before the adjacency is complete.",
        "The first state is Down, where no hello packet has been received yet.",
        "When a router receives a hello packet it moves the neighbor to the Init state.",
        "Once the router sees its own router ID in the received hello packet,",
        "the neighbor moves to the 2-Way state.",
        "After the database exchange finishes, the neighbor reaches the Full state.",
    ], None),
    ("Designated Router Election", [
        "On a broadcast network OSPF elects a designated router and a backup designated router.",
        "The router with the highest OSPF priority becomes the designated router.",
        "When the priority is equal, the router with the highest router ID wins the election.",
        "A priority of 0 means the router will never become the designated router.",
        "All other routers form a full adjacency only with the DR and the BDR.",
    ], "fig2"),
    ("Verification", [
        "Use the show ip ospf neighbor command to verify the adjacency.",
        "The output below shows the neighbor state and the interface.",
    ], None),
]

CLI_OUTPUT = [
    "R1#show ip ospf neighbor",
    "Neighbor ID     Pri   State           Dead Time   Address         Interface",
    "2.2.2.2           1   FULL/DR         00:00:34    192.168.12.2    GigabitEthernet0/1",
]


def build(out_dir: Path) -> Path:
    out_dir = out_dir / "IGP" / "OSPF"
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir.parent.parent / "_img"
    tmp.mkdir(parents=True, exist_ok=True)
    _topology(tmp / "fig1.png", ["R1", "R2", "R3"], "OSPF neighbor topology")
    _topology(tmp / "fig2.png", ["R1", "R2", "R3"], "DR/BDR election topology")

    pdf = out_dir / "OSPF Neighbor Adjacency.pdf"
    c = canvas.Canvas(str(pdf), pagesize=A4)
    for title, body, fig in PAGES:
        c.setFont("Helvetica-Bold", 16)
        c.drawString(2 * cm, H - 2.2 * cm, title)
        c.setFont("Helvetica", 11)
        y = H - 3.2 * cm
        for line in body:
            c.drawString(2 * cm, y, line)
            y -= 0.55 * cm
        if fig:
            y -= 0.6 * cm
            c.drawImage(str(tmp / f"{fig}.png"), 2 * cm, y - 6.2 * cm,
                        width=16 * cm, height=6 * cm)
            y -= 6.6 * cm
            c.setFont("Helvetica-Oblique", 10)
            c.drawString(2 * cm, y, f"Figure: {title} diagram")
        if title == "Verification":
            c.setFont("Courier", 10)
            y -= 0.8 * cm
            for line in CLI_OUTPUT:
                c.drawString(2 * cm, y, line)
                y -= 0.45 * cm
        c.showPage()
    c.save()
    print(f"已生成测试 PDF: {pdf}")
    return pdf


def build_weblike(out_dir: Path, count: int = 8) -> list[Path]:
    """模拟真实课程库:网页导出的 PDF(带站点导航噪声)+ 多层深目录。

    真实的 NetworkLessons PDF 是从网页导出的,每页夹带 Search…、Lessons、
    « »、侧边栏 Lesson Contents 目录等噪声,而且目录深度从 1 层到 6 层不等。
    这个生成器用来验证噪声清理与自适应分组。
    """
    made: list[Path] = []
    tmp = out_dir / "_img"
    tmp.mkdir(parents=True, exist_ok=True)
    _topology(tmp / "web.png", ["R1", "R2", "R3"], "OSPF filtering topology")

    # 故意造出深浅不一的目录:深目录只有 2~3 章(会被自适应合并),浅目录章数够
    layout = [
        ("Cisco/CCIE Enterprise/Unit 1 Infrastructure/1.2 Routing/1.2.f Route filtering", 3),
        ("Cisco/CCIE Enterprise/Unit 1 Infrastructure/1.2 Routing/1.2.a OSPF basics", 2),
        ("Cisco/CCIE Enterprise/Unit 1 Infrastructure/1.3 Switching", 2),
        ("Network Fundamentals", 1),
    ]
    idx = 0
    for rel_dir, n in layout:
        d = out_dir / rel_dir
        d.mkdir(parents=True, exist_ok=True)
        for k in range(n):
            idx += 1
            if idx > count:
                break
            pdf = d / f"{idx:03d} - OSPF Filtering Lesson {idx}.pdf"
            c = canvas.Canvas(str(pdf), pagesize=A4)
            for pg in range(2):
                y = H - 1.6 * cm
                # ---- 站点导航噪声(每页都有)----
                c.setFont("Helvetica", 9)
                c.drawString(2 * cm, y, "Search …")
                y -= 0.9 * cm
                c.setFont("Helvetica-Bold", 16)
                c.drawString(2 * cm, y, f"OSPF Filtering Lesson {idx}")
                y -= 1.0 * cm
                c.setFont("Helvetica", 11)
                for line in [
                    "OSPF supports a number of methods to filter routes on a router.",
                    "As a link-state routing protocol OSPF uses LSAs to build its database.",
                    "Filtering LSAs between areas on an ABR is possible with a filter list.",
                    "The distribute-list command filters routes from entering the table.",
                ]:
                    c.drawString(2 * cm, y, line)
                    y -= 0.55 * cm
                if pg == 0:
                    # ---- 侧边栏目录副本(噪声)----
                    y -= 0.4 * cm
                    c.setFont("Helvetica-Bold", 11)
                    c.drawString(2 * cm, y, "Lesson Contents")
                    y -= 0.5 * cm
                    c.setFont("Helvetica", 10)
                    for t in ["1. Configuration", "1.1. Distribute-list Filtering",
                              "2. Conclusion"]:
                        c.drawString(2 * cm, y, t)
                        y -= 0.45 * cm
                    y -= 0.4 * cm
                    c.drawImage(str(tmp / "web.png"), 2 * cm, y - 5.4 * cm,
                                width=15 * cm, height=5.2 * cm)
                    y -= 5.8 * cm
                    c.setFont("Helvetica", 10)
                    c.drawString(2 * cm, y, "Nothing fancy, we have three routers running OSPF.")
                    y -= 0.8 * cm
                    c.setFont("Courier", 9)
                    for line in ["R1#show running-config | section ospf",
                                 "router ospf 1",
                                 " network 192.168.12.0 0.0.0.255 area 0"]:
                        c.drawString(2 * cm, y, line)
                        y -= 0.42 * cm
                # ---- 页脚导航噪声 ----
                c.setFont("Helvetica", 9)
                c.drawString(2 * cm, 2.2 * cm, "Lessons")
                c.setFont("Helvetica-Bold", 20)
                c.drawString(2 * cm, 1.4 * cm, "«")
                c.drawString(W - 5 * cm, 1.4 * cm, "Filtering »")
                c.showPage()
            c.save()
            made.append(pdf)
    print(f"已生成 {len(made)} 份网页导出风格的测试 PDF")
    return made


def build_vector(out_dir: Path) -> Path:
    """模拟"概念课"的矢量框图 PDF(如神经网络、SDN 架构图)。

    这类图不是位图,而是矩形 + 圆 + 箭头画出来的,`get_images()` 抽不到,
    只能靠矢量区域渲染。而且图里的文字(Input 1 / Neuron / 0 or 1)是独立文本对象,
    裁剪时必须把这些标签一起框进来,否则图就看不懂了。
    """
    out_dir = out_dir / "Automation & Cloud" / "Network Automation" / "Unit 5 AI and ML"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = out_dir / "016 - AI and ML in Networking.pdf"

    c = canvas.Canvas(str(pdf), pagesize=A4)
    for page_no in range(2):
        c.setFont("Helvetica", 9)
        c.drawString(2 * cm, H - 1.6 * cm, "Search …")
        c.setFont("Helvetica-Bold", 15)
        c.drawString(2 * cm, H - 2.6 * cm, "2.2. Neural Networks")
        c.setFont("Helvetica", 11)
        y = H - 3.5 * cm
        for line in [
            "What exactly is a neural network? To understand this, it is best to start",
            "with a simplified example of a neural network with a single neuron.",
            "We call it a neuron, but it is also sometimes referred to as a node or unit.",
        ]:
            c.drawString(2 * cm, y, line)
            y -= 0.55 * cm

        # ---------- 矢量框图:3 个输入框 + 1 个神经元圆 + 1 个输出框 + 箭头 ----------
        top = y - 1.0 * cm
        box_w, box_h = 2.6 * cm, 0.8 * cm
        left_x = 2 * cm
        neuron = (left_x + 5.2 * cm, top - 2.0 * cm)
        out_box = (left_x + 8.6 * cm, top - 2.0 * cm - box_h / 2)

        labels = ["Input 3", "Input 2", "Input 1"] if page_no == 0 else \
                 ["Energy", "Time", "Study Partner"]
        for i, name in enumerate(labels):
            by = top - i * 1.55 * cm - box_h
            c.setFillColorRGB(0.05, 0.28, 0.55)
            c.rect(left_x, by, box_w, box_h, fill=1, stroke=0)
            c.setFillColorRGB(1, 1, 1)
            c.setFont("Helvetica", 9)
            c.drawString(left_x + 0.25 * cm, by + 0.28 * cm, name)
            c.setFillColorRGB(0, 0, 0)
            if page_no == 1:
                c.setFont("Helvetica", 7)
                c.drawString(left_x + 0.25 * cm, by - 0.35 * cm, "0 or 1")
            # 箭头(线 + 箭头三角)
            c.setStrokeColorRGB(0.85, 0.12, 0.12)
            c.setLineWidth(1.6)
            sx, sy = left_x + box_w, by + box_h / 2
            ex, ey = neuron[0] - 0.75 * cm, neuron[1]
            c.line(sx, sy, ex, ey)
            c.setFillColorRGB(0.85, 0.12, 0.12)
            p = c.beginPath()
            p.moveTo(ex, ey)
            p.lineTo(ex - 0.18 * cm, ey + 0.12 * cm)
            p.lineTo(ex - 0.18 * cm, ey - 0.12 * cm)
            p.close()
            c.drawPath(p, fill=1, stroke=0)
            c.setFillColorRGB(0, 0, 0)

        c.setFillColorRGB(0.09, 0.55, 0.24)
        c.circle(neuron[0], neuron[1], 0.75 * cm, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica", 8)
        c.drawString(neuron[0] - 0.5 * cm, neuron[1] - 0.1 * cm, "Neuron")

        c.setFillColorRGB(0.05, 0.28, 0.55)
        c.rect(out_box[0], out_box[1], box_w, box_h, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica", 9)
        c.drawString(out_box[0] + 0.25 * cm, out_box[1] + 0.28 * cm, "Output")
        c.setStrokeColorRGB(0.85, 0.12, 0.12)
        c.line(neuron[0] + 0.75 * cm, neuron[1], out_box[0], neuron[1])
        c.setFillColorRGB(0, 0, 0)
        if page_no == 1:
            c.setFont("Helvetica", 7)
            c.drawString(out_box[0] + 0.25 * cm, out_box[1] - 0.4 * cm, "Total input:")
            c.drawString(out_box[0] + 0.25 * cm, out_box[1] - 0.75 * cm, "=> 2 = yes")

        c.setFont("Helvetica", 11)
        yy = out_box[1] - 2.2 * cm
        for line in [
            "A simple neural network like this with a single output is called a perceptron.",
            "In this example, the inputs are all equally important to the decision.",
        ]:
            c.drawString(2 * cm, yy, line)
            yy -= 0.55 * cm

        c.setFont("Helvetica", 9)
        c.drawString(2 * cm, 2.0 * cm, "Lessons")
        c.showPage()
    c.save()
    print(f"已生成矢量框图测试 PDF: {pdf}")
    return pdf


def build_scanned(out_dir: Path) -> Path:
    """再造一份"扫描件"PDF(整页是图片、没有文本层),用来验证 audit 能把它剔除。"""
    out_dir = out_dir / "IGP" / "OSPF"
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir.parent.parent / "_img"
    tmp.mkdir(parents=True, exist_ok=True)

    page_img = tmp / "scanned-page.png"
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    for i in range(28):                    # 用线条模拟扫描出来的文字行
        y = 160 + i * 52
        d.line([(120, y), (1100 - (i % 5) * 90, y)], fill=(70, 70, 70), width=6)
    d.ellipse([420, 1180, 820, 1420], outline=(40, 80, 140), width=8)
    img.save(page_img)

    pdf = out_dir / "OSPF Scanned Handout.pdf"
    c = canvas.Canvas(str(pdf), pagesize=A4)
    for _ in range(3):
        c.drawImage(str(page_img), 0, 0, width=W, height=H)
        c.showPage()
    c.save()
    print(f"已生成扫描件测试 PDF: {pdf}")
    return pdf


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tests/_tmp/source")
    build(target)
    if "--with-scanned" in sys.argv:
        build_scanned(target)
    if "--with-weblike" in sys.argv:
        build_weblike(target)
    if "--with-vector" in sys.argv:
        build_vector(target)
