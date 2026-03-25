"""手机扫码 Web 服务：手机浏览器扫码 → 桌面程序"""
import threading
import socket
import ssl
import json
import tempfile
import os
from flask import Flask, Response

# 回调函数，由主程序设置
_on_isbn = None
_on_price = None

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
button.start{margin:15px;padding:12px 40px;font-size:16px;border:none;border-radius:10px;background:#fff;color:#667eea;font-weight:bold;cursor:pointer}
</style>
</head>
<body>
<h2>扫描图书条码</h2>
<div id="reader"></div>
<button class="start" id="startBtn" onclick="startScan()">点击开始扫码</button>
<div id="result">点击上方按钮开始</div>
<div id="priceBox" style="display:none;margin:10px auto;width:90vw;max-width:400px;text-align:center">
  <label style="display:inline-block;padding:10px 25px;background:rgba(255,255,255,0.3);border-radius:10px;cursor:pointer;font-size:15px;backdrop-filter:blur(10px)">
    拍照识别价格
    <input type="file" accept="image/*" capture="environment" id="priceInput" style="display:none" onchange="ocrPrice(this)">
  </label>
  <div id="priceResult" style="margin-top:8px;font-size:16px"></div>
</div>
<div class="history" id="history"></div>
<script>
let lastCode = "";
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
function startScan() {
    document.getElementById("startBtn").style.display = "none";
    document.getElementById("result").textContent = "对准条码即可自动识别";
    document.getElementById("priceBox").style.display = "block";
    const scanner = new Html5Qrcode("reader");
    const config = {
        fps: 15,
        qrbox: function(vw, vh) { return {width: Math.min(vw, 300), height: Math.min(vh, 200)}; },
        experimentalFeatures: { useBarCodeDetectorIfSupported: true }
    };
    scanner.start(
        {facingMode: "environment"},
        config,
        (text, result) => { send(text); },
        (err) => {}
    ).catch(e => {
        document.getElementById("result").textContent = "摄像头启动失败: " + e;
    });
}
function ocrPrice(input) {
    if (!input.files[0]) return;
    const pr = document.getElementById("priceResult");
    pr.textContent = "识别中...";
    const reader = new FileReader();
    reader.onload = function() {
        fetch("/ocr_price", {method:"POST", headers:{"Content-Type":"application/json"},
            body:JSON.stringify({isbn: lastCode, image: reader.result})
        }).then(r=>r.json()).then(d => {
            if (d.price) {
                pr.textContent = "识别价格: " + d.price + " 元";
                pr.style.color = "#4CAF50";
                fetch("/scan", {method:"POST", headers:{"Content-Type":"application/json"},
                    body:JSON.stringify({price: d.price})});
            } else {
                pr.textContent = "未识别到价格，请手动输入";
                pr.style.color = "#ff9800";
            }
        }).catch(e => { pr.textContent = "识别失败"; });
    };
    reader.readAsDataURL(input.files[0]);
    input.value = "";
}
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


@app.route("/ocr_price", methods=["POST"])
def ocr_price():
    from flask import request
    import base64
    import re
    import requests as req
    try:
        data = request.get_json(silent=True)
        if not data or not data.get("image"):
            return json.dumps({"price": ""})

        # base64 图片数据
        img_b64 = data["image"].split(",")[1] if "," in data["image"] else data["image"]

        # 压缩图片减少上传体积
        import base64 as b64mod
        from PIL import Image
        import io
        img_bytes = b64mod.b64decode(img_b64)
        img = Image.open(io.BytesIO(img_bytes))
        if max(img.size) > 1500:
            img.thumbnail((1500, 1500))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        img_b64 = b64mod.b64encode(buf.getvalue()).decode("ascii")

        # 调用 PaddleOCR API
        resp = req.post(
            "https://v745g0e1g0272fab.aistudio-app.com/layout-parsing",
            headers={"Authorization": "token 28bf193d7d03c7ba240811ae3f6f10b918a158b9", "Content-Type": "application/json"},
            json={"file": img_b64, "fileType": 1, "useDocOrientationClassify": False, "useDocUnwarping": False, "useChartRecognition": False},
            timeout=30
        )
        text = ""
        if resp.status_code == 200:
            result = resp.json().get("result", {})
            for res in result.get("layoutParsingResults", []):
                text += res.get("markdown", {}).get("text", "")
        print(f"[OCR] 识别文本: {text}")

        # 提取价格
        patterns = [
            r'(?:定价|价格)[：:\s]*[¥￥]?\s*(\d+\.?\d*)',
            r'[¥￥]\s*(\d+\.?\d*)',
            r'(\d+\.\d{2})\s*元',
            r'CNY\s*(\d+\.?\d*)',
            r'(\d{2,6}\.\d{2})',
        ]
        for p in patterns:
            m = re.search(p, text)
            if m:
                price = m.group(1)
                print(f"[OCR] 识别价格: {price}")
                if _on_price:
                    _on_price(price)
                return json.dumps({"price": price})

        return json.dumps({"price": "", "text": text})
    except Exception as e:
        print(f"[OCR] 错误: {e}")
        return json.dumps({"price": "", "error": str(e)})


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


def _generate_self_signed_cert():
    """生成自签名证书用于 HTTPS"""
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, get_local_ip())])
        cert = (x509.CertificateBuilder()
                .subject_name(name).issuer_name(name)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime.utcnow())
                .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
                .add_extension(x509.SubjectAlternativeName([
                    x509.IPAddress(ipaddress.ip_address(get_local_ip()))
                ]), critical=False)
                .sign(key, hashes.SHA256()))

        tmp = tempfile.mkdtemp()
        cert_path = os.path.join(tmp, "cert.pem")
        key_path = os.path.join(tmp, "key.pem")
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        with open(key_path, "wb") as f:
            f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
        return cert_path, key_path
    except ImportError:
        return None, None


import ipaddress


def start(on_isbn_callback, on_price_callback=None):
    """启动 HTTPS Web 服务，返回访问 URL"""
    global _on_isbn, _on_price, _server_thread
    _on_isbn = on_isbn_callback
    _on_price = on_price_callback
    ip = get_local_ip()

    if _server_thread and _server_thread.is_alive():
        return f"https://{ip}:{_port}"

    cert_path, key_path = _generate_self_signed_cert()

    def run():
        if cert_path:
            app.run(host="0.0.0.0", port=_port, threaded=True, ssl_context=(cert_path, key_path))
        else:
            app.run(host="0.0.0.0", port=_port, threaded=True)

    _server_thread = threading.Thread(target=run, daemon=True)
    _server_thread.start()
    return f"https://{ip}:{_port}" if cert_path else f"http://{ip}:{_port}"
