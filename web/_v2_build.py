#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 v2 叠加层组装进 index.html，产出 index.v2.html（单文件自包含）。

用法：  python _v2_build.py
输入：  index.html（真源，不修改） + _v2_layer.css + _v2_dash.js
输出：  index.v2.html

为什么内联而不外链：发布到 ECS 时只拷 index.html 一个文件也不会掉样式与脚本；
也少两次请求。源码仍保留可维护的独立三件套。
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def rd(name):
    with io.open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def main():
    # 允许指定底稿：线上版可能比本地多出补丁（公网精简/移动端/微信提示），
    # 此时必须以线上版为底稿，否则会把线上独有的改动覆盖掉。
    src = sys.argv[1] if len(sys.argv) > 1 else "index.html"
    dstname = sys.argv[2] if len(sys.argv) > 2 else "index.v2.html"
    orig = rd(src)
    css = rd("_v2_layer.css")
    js = rd("_v2_dash.js")

    # —— 注入前闸门：注释里出现字面量闭合标签会打乱解析，直接拦下
    if "</style" in css.lower() or "<style" in css.lower():
        sys.exit("✗ _v2_layer.css 里有字面量 style 标签，会打乱解析")
    if "</script" in js.lower() or "<script" in js.lower():
        sys.exit("✗ _v2_dash.js 里有字面量 script 标签，会打乱解析")
    if "</head>" not in orig or "</body>" not in orig:
        sys.exit("✗ index.html 结构不对：找不到 </head> 或 </body>")

    out = orig.replace("</head>", "<style>\n" + css + "\n</style>\n</head>", 1)
    out = out.replace("</body>", "<script>\n" + js + "\n</script>\n</body>", 1)

    # —— 组装后校验
    if out.lower().count("<style") != out.lower().count("</style>"):
        sys.exit("✗ style 标签不配对")
    if out.lower().count("<script") != out.lower().count("</script>"):
        sys.exit("✗ script 标签不配对")

    ids_o = set(re.findall(r'id="([^"]+)"', orig))
    ids_n = set(re.findall(r'id="([^"]+)"', out))
    lost = ids_o - ids_n
    if lost:
        sys.exit("✗ 原 id 丢失：%s" % sorted(lost))

    for m in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", orig, re.S):
        if m.strip() and m not in out:
            sys.exit("✗ 原内联脚本未原样保留")

    dst = os.path.join(HERE, dstname)
    with io.open(dst, "w", encoding="utf-8", newline="") as f:
        f.write(out)

    print("✓ 已生成 " + dstname + "（底稿 " + src + "）")
    print("  体积: %d → %d 字节（+%d）" % (len(orig), len(out), len(out) - len(orig)))
    print("  原 id 保留: %d 个，无丢失" % len(ids_o))
    print("  原内联脚本: 原样保留，一字未改")
    print("  style 标签: %d 对；script 标签: %d 对" % (
        out.lower().count("<style"), out.lower().count("<script")))


if __name__ == "__main__":
    main()
