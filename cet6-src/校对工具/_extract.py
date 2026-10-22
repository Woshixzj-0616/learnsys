# -*- coding: utf-8 -*-
"""从保存的网页 HTML 中提取英文行（临时工具）。用法：python _extract.py in.html out.txt"""
import re, html, sys

def extract(path):
    t = open(path, encoding='utf-8', errors='ignore').read()
    t = re.sub(r'<script.*?</script>', '', t, flags=re.S)
    t = re.sub(r'<style.*?</style>', '', t, flags=re.S)
    t = re.sub(r'<br\s*/?>', '\n', t, flags=re.I)
    t = re.sub(r'</p>', '\n', t, flags=re.I)
    t = html.unescape(re.sub(r'<[^>]+>', '\n', t))
    out = []
    for raw in t.splitlines():
        line = raw.strip().replace('​', '').replace('\xa0', ' ')
        if not line:
            continue
        # 去掉纯符号/乱码行
        letters = sum(c.isalpha() and ord(c) < 128 for c in line)
        if letters < 3 or ' ' not in line:
            continue
        # 英文占比够高：字母+空格+常用标点应占绝大多数
        good = sum(1 for c in line if (c.isalnum() and ord(c) < 128) or c in " .,'’?!:;-\"()%$")
        if good / len(line) < 0.75:
            continue
        words = re.findall(r"[A-Za-z][A-Za-z'’\-]+", line)
        if len(words) < 2 and not re.match(r'(M|W|Man|Woman)\s*[:：]', line):
            continue
        # 非 ASCII 字符极少
        non_ascii = sum(1 for c in line if ord(c) > 127)
        if non_ascii > max(3, len(line) * 0.15):
            continue
        # 去掉单元标题、题目行
        if re.match(r'^(Conversation|Passage|Recording|Section|Part)\s+(One|Two|Three|Four|\d+)\b', line, re.I):
            continue
        if re.match(r'^(Questions?\s+\d|Question\s+\d+[:：]|\d+\.\s)', line, re.I):
            break
        # 去掉说话人前缀
        line = re.sub(r'^(M|W|Man|Woman)\s*[:：]\s*', '', line)
        out.append(line)
    return out

if __name__ == '__main__':
    lines = extract(sys.argv[1])
    text = '\n'.join(lines) + '\n'
    if len(sys.argv) > 2:
        open(sys.argv[2], 'w', encoding='utf-8').write(text)
        print(f'{sys.argv[2]}: {len(lines)} 行')
    else:
        print(text)
