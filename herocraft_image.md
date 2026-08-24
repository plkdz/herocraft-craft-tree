# herocraft_image.py

文件职责：把生成后的 HeroCraft HTML 自动展开并渲染成完整 PNG。

工作流程：

- 查找本机 Edge 或 Chrome；也可用环境变量 `HEROCRAFT_BROWSER` 指定浏览器路径。
- 复制一份临时 HTML，把初始脚本改成 `setAllDetails(true)`，用于截图前全部展开；调用方负责用完后删除临时文件。
- 通过 Chrome DevTools Protocol 打开 HTML，截图前解除 `.tree-viewport` 的固定视口裁剪并清掉平移缩放；普通表格页面没有树控件时会跳过树专用处理。
- 读取解除裁剪后的页面完整宽高，并同时参考 `main` 区域边界，避免顺序表这类非树页面截图被裁短。
- 使用 `Page.captureScreenshot(captureBeyondViewport=true)` 分块截图，再用 Pillow 拼成完整 PNG，避免只截当前视口和浏览器单张截图尺寸限制。
- 分块截图时会输出图片尺寸、总块数和当前进度。
- DevTools 连接保留较长读超时，避免大图生成超过 10 秒时误判失败。

入口函数：

- `image_output_path()`：把 HTML 输出路径转换成默认 PNG 路径。
- `write_expanded_html_for_image()`：生成截图专用的全部展开 HTML。
- `render_html_image()`：启动浏览器并写出 PNG。

<!-- code-sync:start -->
## 代码同步清单

> 本节由对应 `.py` 的当前结构同步，用于存档核对。

来源：`herocraft_image.py`

### 类和类型
- 无

### 函数
- `def image_output_path(output_path: str) -> str`
- `def find_browser_executable() -> str`
- `def write_expanded_html_for_image(html_path: str) -> str`
- `def websocket_frame(payload: str) -> bytes`
- `def read_exact(connection: socket.socket, size: int) -> bytes`
- `def read_websocket_text(connection: socket.socket) -> str`
- `def connect_devtools(websocket_url: str) -> socket.socket`
- `def devtools_call(connection: socket.socket, message_id: int, method: str, params: dict[str, object] | None=None) -> dict[str, object]`
- `def capture_png_tile(connection: socket.socket, message_id: int, x: int, y: int, width: int, height: int) -> bytes`
- `def save_tiled_screenshot(connection: socket.socket, next_message_id: int, image_path: str, page_width: int, page_height: int) -> int`
- `def free_port() -> int`
- `def wait_for_page_devtools(port: int) -> str`
- `def cleanup_browser_profile(path: str) -> None`
- `def render_html_image(html_path: str, image_path: str, *, width: int, height: int) -> None`

### 命令行参数
- 无
<!-- code-sync:end -->
