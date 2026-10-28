"""Generate the report's editable vector and high-resolution fishbone diagram."""

from html import escape
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUTPUT = Path(__file__).resolve().parent
WIDTH, HEIGHT, SCALE = 1920, 1080, 2
INK = "#21372F"
MUTED = "#5B7067"
GREEN = "#227451"
STRUCTURE = "#7A9889"
image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), "#FFFFFF")
draw = ImageDraw.Draw(image)
svg = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
    f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">',
    '<title id="title">社区 Issue 测试转化的影响因素鱼骨图</title>',
    '<desc id="desc">从信息获取、分析方法、环境配置、人员协作、工作流程、知识沉淀六方面，'
    '梳理社区 Issue 难以高效转化为测试输入的潜在原因。此图用于背景分析，不能代替根因验证。</desc>',
    f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#FFFFFF"/>',
]


def line(x1, y1, x2, y2, color=STRUCTURE, width=3):
    draw.line(tuple(int(v * SCALE) for v in (x1, y1, x2, y2)), fill=color, width=width * SCALE)
    svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
               f'stroke="{color}" stroke-width="{width}" stroke-linecap="round"/>')


def text(x, y, value, size=25, color=INK, bold=False, anchor="start"):
    font_path = "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"
    font = ImageFont.truetype(font_path, size * SCALE)
    draw.text((x * SCALE, y * SCALE), value, fill=color, font=font,
              anchor={"middle": "ms", "end": "rs"}.get(anchor, "ls"))
    svg.append(f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" '
               f'font-family="Microsoft YaHei, Noto Sans CJK SC, sans-serif" '
               f'font-weight="{700 if bold else 400}" text-anchor="{anchor}">{escape(value)}</text>')


def rectangle(x1, y1, x2, y2, fill, stroke=None):
    draw.rectangle(tuple(int(v * SCALE) for v in (x1, y1, x2, y2)), fill=fill,
                   outline=stroke, width=2 * SCALE)
    stroke_attr = f' stroke="{stroke}" stroke-width="2"' if stroke else ""
    svg.append(f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" '
               f'fill="{fill}"{stroke_attr}/>')


def polygon(points, fill):
    draw.polygon([(int(x*SCALE), int(y*SCALE)) for x, y in points], fill=fill)
    svg.append(f'<polygon points="{" ".join(f"{x},{y}" for x,y in points)}" fill="{fill}"/>')


text(92, 92, "社区 Issue 为什么难以高效转化为测试输入？", 44, bold=True)
text(94, 143, "issue-tracker 建设背景 · 潜在影响因素分析", 25, color=MUTED)

# The spine ends at the problem, and each primary branch collects three factors.
line(112, 540, 1578, 540, GREEN, 5)
polygon([(1578, 540), (1559, 528), (1559, 552)], GREEN)
rectangle(1584, 443, 1840, 637, "#EAF3EE", "#C6DCD0")
text(1712, 490, "核心问题", 24, GREEN, True, "middle")
text(1712, 535, "社区 Issue 难以", 28, bold=True, anchor="middle")
text(1712, 577, "高效转化为测试输入", 25, bold=True, anchor="middle")

groups = [
    (320, True, "信息获取", ["新增与更新需人工跟进", "正文和评论信息分散", "历史问题容易遗漏"]),
    (770, True, "分析方法", ["分诊标准不够统一", "价值与复现性判断耗时", "资料整理存在重复投入"]),
    (1220, True, "环境配置", ["模型与量化组合多", "硬件与软件版本交织", "关键复现参数不完整"]),
    (320, False, "人员协作", ["分析依赖个人经验", "交接时需要重复阅读", "处理进展不易共享"]),
    (770, False, "工作流程", ["问题逐条处理耗时", "批量整理依赖手工", "社区反馈与测试衔接弱"]),
    (1220, False, "知识沉淀", ["分析结论分散存放", "同类问题经验难检索", "测试用例转化缺少关联"]),
]

for center, upper, category, causes in groups:
    endpoint_y = 265 if upper else 815
    joint_x = center + 190
    line(center, endpoint_y, joint_x, 540, STRUCTURE, 3)
    text(center, 232 if upper else 870, category, 31, GREEN, True, "middle")
    for index, cause in enumerate(causes):
        y = (345 + index*76) if upper else (735 - index*76)
        fraction = (y-endpoint_y)/(540-endpoint_y)
        x = center + fraction*190
        start_x = x - 300
        line(start_x, y, x, y, STRUCTURE, 2)
        text(start_x+4, y-13, cause, 24)

line(94, 955, 1840, 955, "#DCE6E0", 2)
text(94, 999, "用于汇报：说明建设背景与痛点；潜在原因需要结合实际流程验证。", 23, MUTED)
text(1840, 999, "项目建设前的工作场景", 22, MUTED, anchor="end")

svg.append("</svg>")
(OUTPUT / "issue-tracker-fishbone.svg").write_text("\n".join(svg), encoding="utf-8")
image.save(OUTPUT / "issue-tracker-fishbone.png", dpi=(240, 240))
print(OUTPUT / "issue-tracker-fishbone.svg")
print(OUTPUT / "issue-tracker-fishbone.png")
