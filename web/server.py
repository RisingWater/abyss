#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大肥鱼 3D 查看器 · 本地静态服务器

用法：
    python3 server.py                # 默认 127.0.0.1:8899
    python3 server.py --port 9000    # 换端口
    python3 server.py --host 0.0.0.0 # 允许同一 WiFi 下其他设备访问
    python3 server.py --open         # 启动后自动打开浏览器

必须通过这个服务器打开 index.html，不能直接双击（file:// 协议会被浏览器
的CORS 策略拦截 ES Module 与 GLB，导致白屏）。
"""

import argparse
import http.server
import os
import socket
import socketserver
import sys
import threading
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PORT = 8899

# 控制台配色（Windows / 非 TTY 环境自动降级为空串）
class C:
    OK = "\033[32m" if sys.stdout.isatty() else ""
    DIM = "\033[2m" if sys.stdout.isatty() else ""
    BOLD = "\033[1m" if sys.stdout.isatty() else ""
    ERR = "\033[31m" if sys.stdout.isatty() else ""
    OFF = "\033[0m" if sys.stdout.isatty() else ""


class Handler(http.server.SimpleHTTPRequestHandler):
    """静态文件处理器：固定根目录为脚本所在目录，并屏蔽缓存方便改完刷新就生效。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def log_message(self, fmt, *args):
        # 自定义访问日志：GET 200 用暗色，4xx/5xx 用红色标出
        code = str(args[1]) if len(args) > 1 else ""
        mark = C.OK if code.startswith("2") else C.ERR
        sys.stdout.write("%s  %s%s%s\n" % (C.DIM, mark, fmt % args, C.OFF))
        sys.stdout.flush()


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True      # 端口 TIME_WAIT 也能立刻重启


def local_ip() -> str:
    """取本机在局域网中的 IP（拿不到就返回 127.0.0.1）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("223.5.5.5", 80))    # 不会真的发包，只为让系统选出口网卡
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def banner(host: str, port: int) -> None:
    ip = local_ip()
    show_lan = host in ("0.0.0.0", "::")
    print()
    print("%s%s  大肥鱼 3D 查看器 · 服务器已启动%s" % (C.BOLD, C.OK, C.OFF))
    print("%s  根目录：%s%s" % (C.DIM, ROOT, C.OFF))
    print()
    if show_lan:
        print("  %s本机访问%s   http://127.0.0.1:%d/index.html" % (C.BOLD, C.OFF, port))
        if ip != "127.0.0.1":
            print("  %s局域网访问%s http://%s:%d/index.html" % (C.BOLD, C.OFF, ip, port))
    else:
        print("  %s网页地址%s   http://127.0.0.1:%d/index.html" % (C.BOLD, C.OFF, port))
        print("%s  （想让同学用手机/电脑访问，加 --host 0.0.0.0）%s" % (C.DIM, C.OFF))
    print()
    print("%s  按 Ctrl+C 停止%s" % (C.DIM, C.OFF))
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="大肥鱼 3D 查看器本地服务器")
    ap.add_argument("--port", "-p", type=int, default=DEFAULT_PORT, help="端口（默认 %d）" % DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1；局域网用 0.0.0.0）")
    ap.add_argument("--open", "-o", action="store_true", help="启动后自动打开浏览器")
    args = ap.parse_args()

    index = os.path.join(ROOT, "index.html")
    if not os.path.isfile(index):
        print("%s错误：同目录下找不到 index.html%s" % (C.ERR, C.OFF))
        return 1
    if not os.path.isfile(os.path.join(ROOT, "assets", "dafeiyu.glb")):
        print("%s警告：找不到 assets/dafeiyu.glb，页面会提示模型载入失败%s" % (C.ERR, C.OFF))

    # 端口占用时自动往后找，最多试 20 个
    port = args.port
    for _ in range(20):
        if port_available("127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host, port):
            break
        print("%s端口 %d 被占用，尝试 %d …%s" % (C.DIM, port, port + 1, C.OFF))
        port += 1
    else:
        print("%s错误：%d~%d 端口都被占用%s" % (C.ERR, args.port, port, C.OFF))
        return 1

    url = "http://127.0.0.1:%d/index.html" % port
    banner(args.host, port)

    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        with Server((args.host, port), Handler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n%s已停止%s" % (C.DIM, C.OFF))
    except OSError as e:
        print("%s启动失败：%s%s" % (C.ERR, e, C.OFF))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())