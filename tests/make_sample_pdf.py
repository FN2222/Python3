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
