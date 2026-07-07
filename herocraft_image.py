from __future__ import annotations

# 文件职责：把生成后的 HeroCraft HTML 通过 Edge/Chrome DevTools 渲染成完整 PNG。

import base64
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.request


def image_output_path(output_path: str) -> str:
    stem, _ = os.path.splitext(output_path)
    return f"{stem}.png"


def find_browser_executable() -> str:
    candidates = [
        os.environ.get("HEROCRAFT_BROWSER", ""),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    raise RuntimeError("找不到 Edge/Chrome。可用环境变量 HEROCRAFT_BROWSER 指定浏览器路径。")


def write_expanded_html_for_image(html_path: str) -> str:
    stem, extension = os.path.splitext(html_path)
    expanded_path = f"{stem}_image{extension or '.html'}"
    with open(html_path, "r", encoding="utf-8") as file:
        content = file.read()
    content = content.replace("layoutTreeLines();\n    resetView();", "setAllDetails(true);")
    with open(expanded_path, "w", encoding="utf-8") as file:
        file.write(content)
    return expanded_path


def websocket_frame(payload: str) -> bytes:
    data = payload.encode("utf-8")
    length = len(data)
    mask = os.urandom(4)
    if length < 126:
        header = bytes([0x81, 0x80 | length])
    elif length < 65536:
        header = bytes([0x81, 0x80 | 126]) + length.to_bytes(2, "big")
    else:
        header = bytes([0x81, 0x80 | 127]) + length.to_bytes(8, "big")
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
    return header + mask + masked


def read_exact(connection: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = connection.recv(remaining)
        if not chunk:
            raise RuntimeError("浏览器调试连接已断开")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_websocket_text(connection: socket.socket) -> str:
    first, second = read_exact(connection, 2)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = int.from_bytes(read_exact(connection, 2), "big")
    elif length == 127:
        length = int.from_bytes(read_exact(connection, 8), "big")
    mask = read_exact(connection, 4) if masked else b""
    payload = read_exact(connection, length)
    if masked:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    if opcode == 8:
        raise RuntimeError("浏览器调试连接已关闭")
    if opcode != 1:
        return read_websocket_text(connection)
    return payload.decode("utf-8")


def connect_devtools(websocket_url: str) -> socket.socket:
    if not websocket_url.startswith("ws://"):
        raise RuntimeError(f"不支持的调试地址：{websocket_url}")
    host_and_path = websocket_url[len("ws://") :]
    host_port, path = host_and_path.split("/", 1)
    host, raw_port = host_port.rsplit(":", 1)
    connection = socket.create_connection((host, int(raw_port)), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET /{path} HTTP/1.1\r\n"
        f"Host: {host_port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    connection.sendall(request.encode("ascii"))
    response = b""
    while b"\r\n\r\n" not in response:
        response += connection.recv(4096)
    if b" 101 " not in response.split(b"\r\n", 1)[0]:
        raise RuntimeError("连接浏览器调试协议失败")
    return connection


def devtools_call(
    connection: socket.socket,
    message_id: int,
    method: str,
    params: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"id": message_id, "method": method}
    if params is not None:
        payload["params"] = params
    connection.sendall(websocket_frame(json.dumps(payload)))
    while True:
        message = json.loads(read_websocket_text(connection))
        if message.get("id") != message_id:
            continue
        if "error" in message:
            raise RuntimeError(f"{method} 失败：{message['error']}")
        result = message.get("result")
        return result if isinstance(result, dict) else {}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def wait_for_page_devtools(port: int) -> str:
    url = f"http://127.0.0.1:{port}/json/list"
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                targets = json.loads(response.read().decode("utf-8"))
            if isinstance(targets, list):
                for target in targets:
                    if not isinstance(target, dict) or target.get("type") != "page":
                        continue
                    websocket_url = target.get("webSocketDebuggerUrl")
                    if isinstance(websocket_url, str):
                        return websocket_url
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("等待浏览器页面调试端口超时")


def render_html_image(html_path: str, image_path: str, *, width: int, height: int) -> None:
    browser = find_browser_executable()
    html_url = "file:///" + os.path.abspath(html_path).replace("\\", "/")
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="herocraft-browser-") as user_data_dir:
        process = subprocess.Popen(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={user_data_dir}",
                f"--window-size={width},{height}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            connection = connect_devtools(wait_for_page_devtools(port))
            try:
                message_id = 1
                devtools_call(connection, message_id, "Page.enable")
                message_id += 1
                devtools_call(connection, message_id, "Page.navigate", {"url": html_url})
                message_id += 1
                time.sleep(1)
                metrics_result = devtools_call(
                    connection,
                    message_id,
                    "Runtime.evaluate",
                    {
                        "expression": "(() => { setAllDetails(true); return { width: Math.ceil(document.documentElement.scrollWidth), height: Math.ceil(document.documentElement.scrollHeight) }; })()",
                        "returnByValue": True,
                    },
                )
                message_id += 1
                value = metrics_result.get("result", {}).get("value", {})
                page_width = max(width, int(value.get("width", width))) if isinstance(value, dict) else width
                page_height = max(height, int(value.get("height", height))) if isinstance(value, dict) else height
                devtools_call(
                    connection,
                    message_id,
                    "Emulation.setDeviceMetricsOverride",
                    {
                        "width": page_width,
                        "height": page_height,
                        "deviceScaleFactor": 1,
                        "mobile": False,
                    },
                )
                message_id += 1
                time.sleep(0.2)
                screenshot = devtools_call(
                    connection,
                    message_id,
                    "Page.captureScreenshot",
                    {
                        "format": "png",
                        "fromSurface": True,
                        "captureBeyondViewport": True,
                    },
                )
                data = screenshot.get("data")
                if not isinstance(data, str):
                    raise RuntimeError("浏览器没有返回截图数据")
                with open(image_path, "wb") as file:
                    file.write(base64.b64decode(data))
            finally:
                connection.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
