<div align="center">

<img src="docs/screenshots/icon.png" width="96" alt="表情包工坊" />

# 表情包工坊 · StickerWorkshop

**一张照片进，一整套能上架微信表情开放平台的动态表情包出。**

不用敲命令行——上传照片生成卡通形象，AI 写好整套文案，逐张生成动图，
合成 GIF、跑微信规范检查、打出投稿包，全程图形界面点一点。

[![Release](https://img.shields.io/github/v/release/CaroNiu/StickerWorkshop?label=%E6%9C%80%E6%96%B0%E7%89%88%E6%9C%AC)](https://github.com/CaroNiu/StickerWorkshop/releases/latest)
[![Platform](https://img.shields.io/badge/%E5%B9%B3%E5%8F%B0-Windows%20%7C%20macOS-blue)](#-下载安装)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

**这是用它做出来的成品（真实项目输出，非宣传图）：**

<table><tr>
<td><img src="docs/demo/01.gif" width="200" alt="成品动图示例 1"/></td>
<td><img src="docs/demo/04.gif" width="200" alt="成品动图示例 2"/></td>
</tr>
<tr><td align="center">240×240 · 微信投稿规格 · 自动切帧合成</td><td align="center">照片转卡通形象 · 全程同一角色</td></tr>
</table>

> 📦 **[下载示例成品包](../../releases/latest)**（Release 资产 `StickerWorkshop-demo-stickers.zip`）：
> 一套真实项目的投稿素材 + 动图，不需要配置任何 AI 就能先看到成果长什么样。

</div>

---

## ✨ 特性

- **🎨 四步流水线 GUI**：① 定角色 → ② 写文案 → ③ 生成 → ④ 合成·检查·交付，顶部进度总览随时跳转，断点续跑
- **🤖 AI 全程打下手**：AI 生成整套文案初稿（人过目后才保存）；「抽象创意参谋」用错位手法出真正出人意料的选题
- **✎ 单张微调**：某张不满意？不用全抽重摇——右键缩略图「微调这张」，画风构图保持，只改你想改的
- **🔓 不锁定任何厂商**：任意 OpenAI 兼容大模型都能接——OpenAI / DeepSeek / GLM / Qwen / Kimi / 火山方舟 / 中转网关 / 本地 Ollama·vLLM
- **📚 专辑（系列）模式**：一个 IP 形象批量出多套，角色图自动继承、风格统一
- **🔌 无 Key 也能用**：没有 API Key 就复制出图提示词，去 ChatGPT 手动出图，回来点合成
- **✅ 微信规范内置**：平台审核规则做成了检查器，FAIL 清零才建议投稿
- **🛠 三平台自动打包**：推个版本标签，GitHub Actions 自动出 Windows exe + Mac（arm64/Intel）挂到 Release

## 📸 界面一览

| 定角色 | 写文案 |
|---|---|
| ![定角色](docs/screenshots/step1-character.png) | ![写文案](docs/screenshots/step2-copywriting.png) |

| 生成（实时缩略图墙） | 合成·检查·交付（GIF 预览） |
|---|---|
| ![生成](docs/screenshots/step3-generate.png) | ![交付](docs/screenshots/step4-delivery.png) |

<details>
<summary>⚙ 设置界面（两组模型独立配置，任意 OpenAI 兼容服务）</summary>

![设置](docs/screenshots/settings.png)

</details>

## 📥 下载安装

### 方式一：直接下载（推荐，开箱即用）

到 [**Releases**](https://github.com/CaroNiu/StickerWorkshop/releases/latest) 下载对应平台：

| 文件 | 平台 | 用法 |
|---|---|---|
| `StickerWorkshop-vX.X.X-win.exe` | Windows | 双击即用 |
| `StickerWorkshop-vX.X.X-mac-arm64.zip` | macOS (Apple Silicon) | 解压 → 拖进「应用程序」→ **右键 → 打开**（未签名，首次需右键绕过 Gatekeeper） |
| `StickerWorkshop-vX.X.X-mac-intel.zip` | macOS (Intel) | 同上 |

> **不需要安装 Claude / Claude Code，也不需要装任何 skill**——出图提示词、GIF 压缩、
> 微信规范检查逻辑已全部内置在应用里，下载即用。你只需要一个大模型的 API Key（设置里填）。

首次运行在程序旁生成 `config.json`（填模型配置）和 `packs/`（作品目录）；
macOS 的数据在 `~/Library/Application Support/StickerWorkshop/`。

### 方式二：源码运行

```bash
git clone https://github.com/CaroNiu/StickerWorkshop.git
cd StickerWorkshop
pip install -r requirements.txt   # PySide6 + Pillow
python setup_skill.py             # 一键拉取上游 skill 脚本副本（仅首次，见下方说明）
python main.py
```

`setup_skill.py` 做的事：把上游 [imraywang/ray-sticker-shop](https://github.com/imraywang/ray-sticker-shop)
的 `sticker.py`（提示词 + GIF 压缩 + 规范检查逻辑，一个普通 Python 脚本，**不是 Claude 插件、无需 Claude Code**）
复制到本项目的 `vendor/` 目录，源码运行时自动加载。已装过该 skill 的可用
`python setup_skill.py --skill-dir ~/.claude/skills/ray-sticker-shop` 走本地副本。

### 功能依赖一览

| 功能 | 依赖 |
|---|---|
| 全部核心流程（角色图 / 文案 / 生成 / 合成 / 检查 / 投稿包） | exe 内置，源码版由 `vendor/sticker.py` 提供 |
| 大模型调用 | 你自己的 API Key（任意 OpenAI 兼容服务，见下方模型配置） |
| 无 Key 手动出图模式 | 零依赖（复制提示词去 ChatGPT 出图，回来点合成） |

## 🤖 模型配置（不锁定厂商）

通用流水线设计：**任意 OpenAI 兼容大模型都能接**。设置里分「图片生成模型」「文案对话模型」
两组，各自独立填 API Key / 接口地址 / 模型名（可下拉选、也可手填任意模型 ID）：

| 用途 | 链路 | 适用服务 |
|---|---|---|
| 文案对话模型 | OpenAI 兼容 `POST {地址}/chat/completions` | OpenAI / DeepSeek / GLM / Qwen / Kimi / 火山方舟 / 中转聚合网关 / 本地 Ollama·vLLM |
| 图片生成模型 | OpenAI 兼容 multipart `/images/edits` | OpenAI 官方及支持该协议的任意网关 |
| 图片生成模型 | 方舟 JSON `images/generations`（识别到 volces.com 自动切换） | 火山方舟标准入口与 Coding 套餐入口 |

默认值面向 OpenAI 官方（`gpt-image-1` / `gpt-4o-mini`，接口地址留空即可）；换其他服务只需改
这三项配置——流水线本身（提示词、GIF 合成、规范检查）不感知厂商。两组模型可以用不同账号的 Key。

> ⚠ `config.json` 以明文保存 API Key（已进 `.gitignore`），勿提交、勿外传。

## 🚀 使用流程

| 步骤 | 做什么 | 小技巧 |
|---|---|---|
| **① 定角色** | 拖入照片 → 生成卡通角色图 | 这张图是整套形象的锚，不满意就重抽 |
| **② 写文案** | 「✨ AI 生成整套文案」→ 人工过目修改 → 保存；「💡 抽象创意参谋」可先出选题 | 名称 ≤8 字；含义词 ≤4 字不重复；动作写具体身体动作 |
| **③ 生成** | 先「预估花费」再「开始生成」；实时缩略图墙逐张上墙 | 已生成的自动跳过；某张不满意**右键微调**或填序号重抽 |
| **④ 合成·检查·交付** | 一键合成 GIF → 规范检查（FAIL 必须清零）→ 打开投稿目录 | 投稿包、预览 HTML、上架文案一并产出 |

## 🎁 特色功能

### ✎ 单张微调
第③步缩略图右键 →「✎ 微调这张…」：以**该图本身**为参考图重新生成，画风、构图、角色形象
保持不变，只按你的指令调整（快捷指令一键追加：表情更夸张 / 更Q更圆润 / 色调更暖…）。
比「重抽」（全随机）可控得多，费用 ≈ 一次普通生成。

### 💡 抽象创意参谋
设计对标熊猫头、金馆长这类国民级表情包的底层逻辑：**每张图都是一次社交动作**——怼人 / 认怂 / 阴阳
三组姿态各出 4 条，「想不出该在哪句话后面发它」的选题直接淘汰，温和治愈系等于失败。在姿态之上用
**错位手法**造词——自造伪术语（电子青菜）、物种错位（精神水豚）、状态合成词（班味很重）、身体化情绪
（心口堵车）、反向祝福（祝你掉线）、具体到荒诞（键盘出汗）——烂大街的首想词全部禁用。
勾选心仪的选题，一键填入灵感提示。

### 📚 专辑（系列）模式
「文件 → 专辑管理器」：一个专辑 = 多套同形象表情包。新建套自动复制专辑里最新的角色图
（系列形象一致）、风格继承专辑设定，每套带独立的状态标签。散装项目互不影响。

## 📦 从源码打包

PyInstaller 不支持交叉编译，本机是什么平台就打什么包（GitHub Actions 打包见
`.github/workflows/release.yml`，推 `v*` 标签自动出三平台 Release）：

```bash
pip install PySide6 Pillow pyinstaller
python build_exe.py    # Windows 出单文件 exe；macOS 出 .app → zip
```

应用图标在打包时由 `theme.py` 的矢量绘制自动渲染（Windows `.ico` / macOS `.icns`），仓库无需二进制素材。

## 🧪 测试

```bash
for f in test_*.py; do python "$f"; done
```

覆盖：skill 加载 / 项目管理 / 文案与创意 JSON 容错（剥 `<think>`、平衡扫描、截断修复、自动纠偏重试）/
微调链路 / 方舟路由分发 / 缩略图墙 / 专辑模式 / GUI 僵尸线程免疫 / 厂商通用化。

## ❓ FAQ

**要有 API Key 吗？在哪里拿？**
要，但和聊天用的 Key 是同一类东西。任选其一：OpenAI 官方（`gpt-image-1`）、火山方舟（`doubao-seedream`，识别到 volces.com 自动走方舟协议）、任意 OpenAI 兼容网关/本地 Ollama·vLLM。设置里「图片生成模型」和「文案对话模型」两组独立配置，可以用不同账号的 Key。

**一套做下来花多少钱？**
第③步有「预估花费」按钮。默认 12 张 + 5 张素材，按官方 medium 档大约 $0.8 上下（方舟 doubao 系按其计费更便宜）；生成失败的张数不扣费，重抽另算。

**支持哪些模型？换模型要改什么？**
任意 OpenAI 兼容服务都能接，换模型只需改设置里的「模型名」（可下拉或手填任意 ID），流程本身不感知厂商。思考型文案模型（DeepSeek-R1 等）出创意/文案要 1–5 分钟，非思考型（`deepseek-chat` 等）10–30 秒，效果不打折。

**GIF 是什么规格？能上微信吗？**
240×240、500KB 内自动压缩，就是微信表情开放平台的动图规格。程序内置平台规范检查器，FAIL 清零再投稿；注册与提交需本人实名操作。

**一定要做成整套吗？能只出一张吗？**
可以，顶部橙色「⚡ 即兴生成」：参考图 + 一句话想法，约 2 分钟出单张动图，不用建项目。

**需要安装 Claude / Claude Code 吗？**
不需要。下载的 exe 已内置全部逻辑（提示词/GIF 压缩/规范检查），开箱即用；源码运行才需要 `python setup_skill.py` 拉一次脚本副本。

## 🗺 Roadmap

- [x] v1.0.5 戒断按钮 / 形象一致性保护 / 创意参谋
- [x] v1.0.6 ⚡ 即兴模式（参考图 + 想法 → 单张）
- [ ] 即兴模式小批量（一次 3–5 张不同想法）
- [ ] 更多画风预设与「上传示例成品定风格」
- [ ] 宠物专属向导（多照片融合形象）
- [ ] 英文界面 / 国际化
- [ ] 官方演示视频与示例包一键加载

（欢迎在 Issue 里催或投票）

## 📜 合规提醒

只做你有权使用的形象：不做明星、影视动漫游戏角色、二创同人；未成年人照片不投稿（仅可家长私下自用）。
微信注册与提交须本人实名操作，过审由微信决定。

## 🙏 致谢

- [imraywang/ray-sticker-shop](https://github.com/imraywang/ray-sticker-shop) —— 出图提示词、GIF 压缩、微信规范检查全部来自该 skill 本体，本项目是其图形界面封装。**许可说明**：该上游仓库暂未附带 LICENSE（版权归上游作者所有），本仓库的 MIT 仅覆盖 GUI 封装部分；内置分发已注明来源，如需商用请自行与上游作者确认。

## License

[MIT](LICENSE)
