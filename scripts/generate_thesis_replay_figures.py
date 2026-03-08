#!/usr/bin/env python3
from pathlib import Path
import csv

ROOT = Path('/home/gosh/SageFuzz')
FIG_DIR = ROOT / 'docs' / 'thesis_figures'
TABLE_DIR = ROOT / 'docs' / 'thesis_tables'

BAR_DATA = [
    ('完全闭环验证', 3),
    ('可执行但语义待完善', 2),
    ('不可执行', 0),
]

MATRIX_HEADERS = ['程序', '可直接回放', '与 oracle 一致', '区分正确/缺陷实现']
MATRIX_ROWS = [
    ('Stateful Firewall', '√', '√', '√'),
    ('Heavy Hitter Detector', '√', '√', '△'),
    ('Fast Reroute', '√', '√', '√'),
    ('Link Monitor', '√', '△', '√'),
    ('Congestion-Aware Load Balancing', '√', '△', '△'),
]

DETAIL_HEADERS = ['程序', '回放 testcase', '实际观测', '结论']
DETAIL_ROWS = [
    (
        'Stateful Firewall',
        'positive_internal_initiates / negative_external_initiates',
        '正例 SYN 与 SYN-ACK 均成功转发；反例外部 SYN 未到达 h1；bug 版中正例 SYN-ACK 在 s1 入口后被阻断',
        '可直接回放，且能稳定区分正确实现与缺陷实现',
    ),
    (
        'Heavy Hitter Detector',
        'positive_heavy_hitter_triggered',
        '按 testcase 回放 15 个包后，h2 实际仅捕获 10 个包',
        '可直接回放，并与 oracle 一致',
    ),
    (
        'Fast Reroute',
        'fast_reroute_after_link_failure',
        '在执行链路失效动作后，correct 版 h4 捕获 10 个包，bug 版 h4 捕获 0 个包',
        '可直接回放，且能稳定区分正确实现与缺陷实现',
    ),
    (
        'Link Monitor',
        'positive_link_utilization_monitoring',
        'correct 版返回 probe 中 byte_cnt 非零，bug 版为零；但 testcase 的 probe 路径约束不足',
        '可直接回放，但观测路径语义仍需完善',
    ),
    (
        'Congestion-Aware Load Balancing',
        'congestion_reroute',
        '5 个 testcase 包可直接送达 h5；但 testcase 对拥塞注入动作描述过于抽象，未稳定观测到 reroute/feedback 证据',
        '可直接回放，但操作动作语义仍需完善',
    ),
]


def svg_text(x: int, y: int, text: str, size: int = 18, weight: str = 'normal', anchor: str = 'start', fill: str = '#1f2937') -> str:
    return f'<text x="{x}" y="{y}" font-size="{size}" font-family="Arial, Helvetica, sans-serif" font-weight="{weight}" text-anchor="{anchor}" fill="{fill}">{text}</text>'


def draw_bar_chart(out_path: Path) -> None:
    width, height = 1200, 760
    left, right, top, bottom = 120, 80, 120, 120
    plot_w = width - left - right
    plot_h = height - top - bottom
    max_v = max(v for _, v in BAR_DATA)
    bar_w = 180
    gap = (plot_w - bar_w * len(BAR_DATA)) // (len(BAR_DATA) + 1)
    colors = ['#295c77', '#9c6b3c', '#9aa4af']

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fbfaf6"/>',
        svg_text(width // 2, 60, '图4-X 基于最终 testcase 的直接回放验证结果统计', 28, 'bold', 'middle', '#16202a'),
        svg_text(width // 2, 95, '单位：程序个数', 16, 'normal', 'middle', '#475569'),
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#334155" stroke-width="2"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#334155" stroke-width="2"/>',
    ]

    for tick in range(max_v + 1):
        y = top + plot_h - int(plot_h * tick / max_v) if max_v else top + plot_h
        parts.append(f'<line x1="{left - 8}" y1="{y}" x2="{left + plot_w}" y2="{y}" stroke="#d6d3d1" stroke-width="1"/>')
        parts.append(svg_text(left - 18, y + 6, str(tick), 16, 'normal', 'end', '#475569'))

    for i, ((label, value), color) in enumerate(zip(BAR_DATA, colors)):
        x = left + gap * (i + 1) + bar_w * i
        h = 0 if max_v == 0 else int(plot_h * value / max_v)
        y = top + plot_h - h
        parts.append(f'<rect x="{x}" y="{y}" width="{bar_w}" height="{h}" rx="10" fill="{color}"/>')
        parts.append(svg_text(x + bar_w // 2, y - 14, str(value), 22, 'bold', 'middle', '#111827'))
        parts.append(svg_text(x + bar_w // 2, top + plot_h + 40, label, 18, 'bold', 'middle', '#1f2937'))

    parts.append(svg_text(40, top + plot_h // 2, '程序数量', 20, 'bold', 'middle', '#1f2937'))
    parts.append('</svg>')
    out_path.write_text('\n'.join(parts), encoding='utf-8')


def draw_matrix(out_path: Path) -> None:
    width, height = 1500, 860
    left, top = 80, 130
    row_h = 100
    col_w = [420, 250, 250, 320]
    colors = {'√': '#2f6b4f', '△': '#b7791f', '×': '#b42318'}
    bg = {'√': '#e7f4ec', '△': '#fff3d6', '×': '#fde7e9'}

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fbfaf6"/>',
        svg_text(width // 2, 60, '图4-Y 各实验程序直接回放验证状态矩阵', 28, 'bold', 'middle', '#16202a'),
        svg_text(width // 2, 95, '注：√ 表示满足，△ 表示部分满足', 16, 'normal', 'middle', '#475569'),
    ]

    x = left
    for idx, header in enumerate(MATRIX_HEADERS):
        parts.append(f'<rect x="{x}" y="{top}" width="{col_w[idx]}" height="{row_h}" fill="#dbe4ea" stroke="#475569" stroke-width="1.5"/>')
        parts.append(svg_text(x + col_w[idx] // 2, top + 58, header, 22, 'bold', 'middle', '#16202a'))
        x += col_w[idx]

    for r, row in enumerate(MATRIX_ROWS, start=1):
        y = top + row_h * r
        x = left
        for c, cell in enumerate(row):
            fill = '#ffffff' if c == 0 else bg[cell]
            parts.append(f'<rect x="{x}" y="{y}" width="{col_w[c]}" height="{row_h}" fill="{fill}" stroke="#94a3b8" stroke-width="1.2"/>')
            if c == 0:
                parts.append(svg_text(x + 18, y + 60, cell, 21, 'bold', 'start', '#111827'))
            else:
                parts.append(svg_text(x + col_w[c] // 2, y + 64, cell, 34, 'bold', 'middle', colors[cell]))
            x += col_w[c]

    parts.append('</svg>')
    out_path.write_text('\n'.join(parts), encoding='utf-8')


def write_table_files(md_path: Path, csv_path: Path) -> None:
    lines = [
        '# 表4-X 最终 testcase 直接回放实验结果',
        '',
        '| 程序 | 回放 testcase | 实际观测 | 结论 |',
        '| --- | --- | --- | --- |',
    ]
    for row in DETAIL_ROWS:
        lines.append('| ' + ' | '.join(row) + ' |')
    md_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    with csv_path.open('w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.writer(fh)
        writer.writerow(DETAIL_HEADERS)
        writer.writerows(DETAIL_ROWS)


def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    draw_bar_chart(FIG_DIR / 'fig4x_replay_summary.svg')
    draw_matrix(FIG_DIR / 'fig4y_replay_matrix.svg')
    write_table_files(TABLE_DIR / 'table4x_replay_results.md', TABLE_DIR / 'table4x_replay_results.csv')
    print(FIG_DIR / 'fig4x_replay_summary.svg')
    print(FIG_DIR / 'fig4y_replay_matrix.svg')
    print(TABLE_DIR / 'table4x_replay_results.md')
    print(TABLE_DIR / 'table4x_replay_results.csv')


if __name__ == '__main__':
    main()
