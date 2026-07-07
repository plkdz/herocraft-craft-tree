# herocraft_image.py

文件职责：把生成后的 HeroCraft HTML 自动展开并渲染成完整 PNG。

工作流程：

- 查找本机 Edge 或 Chrome；也可用环境变量 `HEROCRAFT_BROWSER` 指定浏览器路径。
- 复制一份临时 HTML，把初始脚本改成 `setAllDetails(true)`，用于截图前全部展开。
- 通过 Chrome DevTools Protocol 打开 HTML，截图前解除 `.tree-viewport` 的固定视口裁剪并清掉平移缩放。
- 读取解除裁剪后的页面完整宽高。
- 使用 `Page.captureScreenshot(captureBeyondViewport=true)` 分块截图，再用 Pillow 拼成完整 PNG，避免只截当前视口和浏览器单张截图尺寸限制。
- DevTools 连接保留较长读超时，避免大图生成超过 10 秒时误判失败。

入口函数：

- `image_output_path()`：把 HTML 输出路径转换成默认 PNG 路径。
- `write_expanded_html_for_image()`：生成截图专用的全部展开 HTML。
- `render_html_image()`：启动浏览器并写出 PNG。
