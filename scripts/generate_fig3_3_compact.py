#!/usr/bin/env python3
from pathlib import Path

OUT = Path('/home/gosh/SageFuzz/docs/thesis_figures/fig3_3_architecture_compact.svg')
OUT.parent.mkdir(parents=True, exist_ok=True)

W, H = 1720, 920
BG = '#fbfaf6'
STROKE = '#334155'
FILL = '#eef3f7'
FILL2 = '#f5efe6'
FILL3 = '#eef5ee'
TEXT = '#0f172a'
MUTED = '#475569'

parts = []
parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
parts.append(f'<rect width="100%" height="100%" fill="{BG}"/>')
parts.append(f'<text x="{W/2}" y="52" text-anchor="middle" font-size="30" font-weight="700" font-family="Arial, Helvetica, sans-serif" fill="{TEXT}">图3-3 P4-BISG 系统总体架构与模块交互关系（缩略版）</text>')
parts.append(f'<text x="{W/2}" y="84" text-anchor="middle" font-size="16" font-family="Arial, Helvetica, sans-serif" fill="{MUTED}">按实际工作流顺序绘制，仅保留主模块标题与关键路径</text>')
parts.append('''
<defs>
  <marker id="arrow" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="#334155"/>
  </marker>
</defs>
''')

def box(x, y, w, h, label, fill, size=24):
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{STROKE}" stroke-width="2.2"/>')
    parts.append(f'<text x="{x+w/2}" y="{y+h/2+8}" text-anchor="middle" font-size="{size}" font-weight="700" font-family="Arial, Helvetica, sans-serif" fill="{TEXT}">{label}</text>')

def arrow(x1, y1, x2, y2, dashed=False, label=None, lx=None, ly=None):
    dash = ' stroke-dasharray="8,7"' if dashed else ''
    parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{STROKE}" stroke-width="2.6" marker-end="url(#arrow)"{dash}/>' )
    if label:
        parts.append(f'<text x="{lx if lx is not None else (x1+x2)/2}" y="{ly if ly is not None else (y1+y2)/2-8}" text-anchor="middle" font-size="15" font-family="Arial, Helvetica, sans-serif" fill="{MUTED}">{label}</text>')

# Layer labels
for x, y, txt in [
    (70, 150, '输入层'),
    (70, 305, '程序上下文层'),
    (70, 500, '生成与调度层'),
    (70, 800, '结果输出层'),
]:
    parts.append(f'<text x="{x}" y="{y}" font-size="22" font-weight="700" font-family="Arial, Helvetica, sans-serif" fill="{MUTED}">{txt}</text>')

# Input layer
box(160, 105, 240, 82, '用户意图输入', FILL, 24)
box(470, 105, 240, 82, '程序输入文件', FILL, 24)
box(780, 105, 210, 82, '运行配置', FILL, 24)

# Context layer
box(500, 255, 380, 92, 'ProgramContext 构建器', FILL2, 28)
box(160, 245, 210, 58, '解析器上下文', FILL2, 20)
box(160, 325, 210, 58, '控制流上下文', FILL2, 20)
box(980, 245, 210, 58, '拓扑上下文', FILL2, 20)
box(980, 325, 210, 58, '控制平面上下文', FILL2, 20)
box(1260, 285, 210, 58, '状态对象上下文', FILL2, 20)

# Scheduler
box(100, 470, 230, 220, '工作流调度', FILL3, 30)

# Sequential chain exact order
box(390, 455, 210, 68, 'Agent1 语义分析', FILL3, 21)
box(680, 455, 220, 68, 'Agent3 任务审查', FILL3, 21)
box(970, 455, 220, 68, 'Agent2 数据包生成', FILL3, 21)
box(1260, 455, 220, 68, 'Agent3 序列审查', FILL3, 21)
box(520, 590, 220, 68, 'Agent4 规则生成', FILL3, 21)
box(840, 590, 220, 68, 'Agent5 规则审查', FILL3, 21)
box(1160, 590, 220, 68, 'Agent6 Oracle 预测', FILL3, 21)

# Output
box(310, 790, 250, 66, '参数修复与校验', FILL, 24)
box(670, 790, 180, 66, '回退生成', FILL, 24)
box(970, 790, 250, 66, 'testcase 输出', FILL, 26)

# Input/context arrows
arrow(590, 187, 690, 255, label='构建上下文', lx=650, ly=220)
arrow(280, 187, 215, 470, label='意图进入流程', lx=200, ly=315)
arrow(885, 187, 250, 470, label='运行控制', lx=530, ly=338)
arrow(690, 347, 215, 470, label='上下文支撑', lx=455, ly=430)

# Context support to chain (single clean support line + dashed accesses)
arrow(690, 347, 495, 455, dashed=True)
arrow(690, 347, 1095, 455, dashed=True)
arrow(690, 347, 630, 590, dashed=True)
arrow(690, 347, 1270, 590, dashed=True)

# Scheduler enters chain once
arrow(330, 525, 390, 489, label='阶段启动', lx=350, ly=495)

# Main exact sequential flow
arrow(600, 489, 680, 489)
arrow(900, 489, 970, 489)
arrow(1190, 489, 1260, 489)
# sequence review to rule generation
arrow(1370, 523, 1370, 624)
arrow(1370, 624, 1380, 624)
arrow(1160, 624, 1060, 624)
arrow(840, 624, 740, 624)
# rule review to oracle
arrow(1060, 624, 1160, 624)

# packet_only shortcut (actual code path)
arrow(1370, 540, 1270, 590, dashed=True, label='packet_only', lx=1370, ly=560)

# Feedback only to immediate previous generator
arrow(680, 515, 495, 515, dashed=True, label='反馈', lx=588, ly=503)
arrow(1260, 515, 1095, 515, dashed=True, label='反馈', lx=1178, ly=503)
arrow(840, 650, 630, 650, dashed=True, label='反馈', lx=735, ly=638)
arrow(1160, 650, 950, 650, dashed=True, label='反馈', lx=1055, ly=638)

# To output
arrow(1270, 658, 1270, 740)
arrow(1270, 740, 1095, 790, label='结果汇总', lx=1185, ly=735)
arrow(560, 823, 670, 823)
arrow(850, 823, 970, 823)
arrow(560, 823, 670, 823, dashed=True, label='失败回退', lx=615, ly=808)

OUT.write_text('\n'.join(parts + ['</svg>']), encoding='utf-8')
print(OUT)
