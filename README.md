# AI-Sticker

用任意 **OpenAI 兼容接口** 一键生成微信表情包：主题规划 → 静图 →（可选）图生视频转 GIF → 横幅/封面/图标 → ZIP。

没配图生视频模型时也能跑，只出静图 PNG。

## 最快启动

系统需要 Python 3.10+。生成动图时还需要 [ffmpeg](https://ffmpeg.org/)（[gifsicle](https://www.lcdf.org/gifsicle/) 可选，用来把 GIF 压到 1MB 内）。

```bash
git clone https://github.com/liangsf/AI-Sticker.git
cd AI-Sticker
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # 然后编辑 .env
python app.py
```

浏览器打开 http://127.0.0.1:8765

macOS 安装 ffmpeg / gifsicle：

```bash
brew install ffmpeg gifsicle
```

## 配置

`.env` 里最少填这 4 项：

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 是 | 接口密钥 |
| `OPENAI_BASE_URL` | 是 | 兼容地址，需包含 `/v1` |
| `CHAT_MODEL` | 是 | 对话模型，用于规划表情 |
| `IMAGE_MODEL` | 是 | 文生图模型 |
| `I2V_MODEL` | 否 | 图生视频模型。留空则只生成静图 |

可选：`STICKER_COUNT`（默认 8）、`HOST` / `PORT`、`VIDEO_DURATION`、`VIDEO_SIZE`、`VIDEO_CONCURRENCY`。

### 接口约定

三条能力都打到同一个 `OPENAI_BASE_URL`：

- 规划：`POST /chat/completions`
- 文生图：`POST /images/generations`（兼容 `url` 或 `b64_json`）
- 图生视频：`POST /videos`（OpenAI Videos API，带 `input_reference` 首帧）

网关只要实现了上述路径，换 Key / Base URL / 模型名即可，不必改代码。

阿里云百炼、OneAPI / NewAPI、自建代理等，把 `OPENAI_BASE_URL` 指到它们的兼容地址即可。若该网关没有 Videos API，把 `I2V_MODEL` 留空。

## 使用

1. 填主题（必填），角色设定可改
2. 点「生成完整表情包」
3. 产物在 `outputs/<job_id>/`，页面可下载 ZIP
4. 中途失败：填入 `job_id` 点「从断点继续」，或：

```bash
curl -X POST http://127.0.0.1:8765/api/resume/<job_id>
```

会跳过已有 PNG / GIF，从缺失步骤接着跑。

## 说明

- 角色设定默认 Q 版可爱风，可在网页修改
- 完整动图流程较慢（图生视频按 `VIDEO_CONCURRENCY` 并发，默认 3）
- 文生图尺寸不被模型支持时，会自动回退到 `1024x1024` 再裁切配套素材

## License

MIT
