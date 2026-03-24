"""手机扫码 Web 服务：手机浏览器扫码 → WebSocket → 桌面程序"""
import threading
import socket
import json
from flask import Flask, Response

# 回调函数，由主程序设置
_on_isbn = None

app = Flask(__name__)
app.logger.disabled = True

import logging
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# SSE 客户端不需要，这里用轮询方式更简单
_latest_isbn = None

SCAN_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>手机扫码</title>
<script src="https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui;background:linear-gradient(135deg,#667eea,#764ba2);min-height:100vh;display:flex;flex-direction:column;align-items:center;color:#fff}
h2{margin:20px 0 10px;font-size:20px}
#reader{width:90vw;max-width:400px;border-radius:12px;overflow:hidden}
#result{margin:15px;padding:15px 25px;background:rgba(255,255,255,0.2);border-radius:10px;font-size:18px;min-height:50px;text-align:center;backdrop-filter:blur(10px)}
.ok{background:rgba(76,175,80,0.5)}
.history{width:90vw;max-width:400px;margin:10px 0;font-size:14px;opacity:0.8}
.history div{padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.2)}
</style>
</head>
<body>
<h2>扫描图书条码</h2>
<div id="reader"></div>
<div id="result">等待扫码...</div>
<div class="history" id="history"></div>
<script>
let lastCode = "", scanner;
function send(isbn) {
    if (isbn === lastCode) return;
    lastCode = isbn;
    const r = document.getElementById("result");
    r.textContent = "已发送: " + isbn;
    r.className = "ok";
    fetch("/scan", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({isbn})});
    const h = document.getElementById("history");
    const d = document.createElement("div");
    d.textContent = new Date().toLocaleTimeString() + " " + isbn;
    h.prepend(d);
    setTimeout(() => { lastCode = ""; }, 2000);
}
scanner = new Html5Qrcode("reader");
scanner.start({facingMode:"environment"}, {fps:10, qrbox:{width:250,height:150}},
    (text) => send(text),
    () => {}
).catch(e => {
    document.getElementById("result").textContent = "无法访问摄像头，请允许权限";
});
</script>
</body>
</html>"""


@app.route("/")
def index():
    return Response(SCAN_PAGE, content_type="text/html")


@app.route("/scan", methods=["POST"])
def scan():
    from flask import request
    data = request.get_json(silent=True)
    if data and data.get("isbn") and _on_isbn:
        _on_isbn(data["isbn"])
    return "ok"


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


_server_thread = None
_port = 5289


def start(on_isbn_callback):
    """启动 Web 服务，返回访问 URL"""
    global _on_isbn, _server_thread
    _on_isbn = on_isbn_callback
    if _server_thread and _server_thread.is_alive():
        return f"http://{get_local_ip()}:{_port}"

    def run():
        app.run(host="0.0.0.0", port=_port, threaded=True)

    _server_thread = threading.Thread(target=run, daemon=True)
    _server_thread.start()
    return f"http://{get_local_ip()}:{_port}"
