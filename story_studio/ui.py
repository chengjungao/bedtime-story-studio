# -*- coding: utf-8 -*-
"""终端输出的小工具。只用标准库。

为什么单独一个文件：Windows 控制台默认 GBK，直接 print 中文在
某些终端会抛 UnicodeEncodeError。这里统一把 stdout 换成 UTF-8，
并且所有输出都过一遍 `say()`，避免到处 try/except。
"""
import io
import sys

WIDTH = 74


def setup():
    """把 stdout / stderr 换成 UTF-8，失败就算了。"""
    for name in ("stdout", "stderr"):
        s = getattr(sys, name, None)
        buf = getattr(s, "buffer", None)
        if buf is None:
            continue
        try:
            setattr(sys, name, io.TextIOWrapper(buf, encoding="utf-8",
                                                errors="replace",
                                                line_buffering=True))
        except Exception:
            pass


def say(msg=u""):
    sys.stdout.write(msg + u"\n")
    sys.stdout.flush()


def rule(ch=u"="):
    say(ch * WIDTH)


def title(msg):
    rule(u"=")
    say(u" " + msg)
    rule(u"=")


def step(n, total, msg):
    say(u"")
    say(u"[%d/%d] %s" % (n, total, msg))


def ok(msg):
    say(u"  [OK]  " + msg)


def warn(msg):
    say(u"  [注意] " + msg)


def bad(msg):
    say(u"  [!!]  " + msg)


def info(msg):
    say(u"        " + msg)


def kv(key, val, width=22):
    say(u"  %-*s %s" % (width, key, val))


def _dw(s):
    """显示宽度：中日韩与全角标点按 2 算，其余按 1。"""
    return sum(2 if ord(c) > 0x2E7F else 1 for c in s)


def _pad(s, width):
    return s + u" " * max(0, width - _dw(s))


def table(headers, rows, indent=2):
    """极简表格。列宽按最长内容算，中文按两个字符宽。"""
    rows = [[u"" if c is None else u"%s" % c for c in r] for r in rows]
    n = len(headers)
    widths = []
    for i in range(n):
        widths.append(max([_dw(headers[i])] +
                          [_dw(r[i]) for r in rows if i < len(r)]))
    lead = u" " * indent
    say(lead + u"  ".join(_pad(headers[i], widths[i]) for i in range(n)))
    say(lead + u"  ".join(u"-" * widths[i] for i in range(n)))
    for r in rows:
        say(lead + u"  ".join(_pad(r[i] if i < len(r) else u"", widths[i])
                              for i in range(n)))
