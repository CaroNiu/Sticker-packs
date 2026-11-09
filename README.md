---
项目: 表情包工坊桌面版
类型: 工具
业务领域: AI 工具链
技术栈: Python/PySide6/Pillow
状态: 可用
创建日期: 2026-11-06
负责人: caro.niu
tags: [表情包, GPT-Image, PySide6, 微信表情开放平台]
---

# 表情包工坊桌面版

[imraywang/ray-sticker-shop](https://github.com/imraywang/ray-sticker-shop) skill 的图形界面封装。
一张照片进，一整套能上架微信表情开放平台的动态表情包出——不用再敲命令行。

## 启动

双击 `启动表情包工坊.bat`（无黑窗口），或命令行 `python main.py`。

首次使用前装依赖：

```bash
pip install -r requirements.txt
```

## 界面流程（四步）

| 步骤 | 做什么 | 对应 skill 命令 |
|---|---|---|
| ① 定角色 | 拖入/浏览照片 → 生成卡通角色图 → 确认形象 | `character` |
| ② 写文案 | **AI 生成整套文案初稿（可配独立文案模型）+ 人工修改**，带字数校验 | 对话模型 + 手写 `pack.json` |
| ③ 生成 | 预估花费 → 开始生成 → 进度条/日志/预计剩余 → 重抽指定序号 | `gen` / `--dry-run` / `--redo` |
| ④ 合成·检查·交付 | 一键合成 → 微信规范检查（FAIL 红/WARN 橙）→ GIF 动图预览 → 打开投稿目录 | `build` / `check` |

顶部四格进度总览常驻显示每步状态（点击跳转）；启动时自动恢复上次项目（断点继续），
「文件 → 最近项目」可切换。

## 依赖的 skill

生成提示词、GIF 压缩、微信规范检查全部来自 skill 本体 `~/.claude/skills/ray-sticker-shop/scripts/sticker.py`（路径可在设置里改），本工具只做编排。skill 更新（`git pull`）后界面功能自动跟随。

装 skill：`git clone https://github.com/imraywang/ray-sticker-shop ~/.claude/skills/ray-sticker-shop`

## 没有OPENAI_API_KEY 也能用

「设置→参数设置」留空 Key，第 ③ 步点「查看出图提示词」复制到 ChatGPT 手动出图，
把图按提示存进 `sheets/01.png` 等位置，回第 ④ 步点合成即可。

## 目录说明

```
config.json    # GUI 设置（含 API Key 明文，已进 .gitignore，勿外传）
packs/         # 每套表情包一个子目录（角色图/精灵图/投稿包/交付zip）
core.py        # skill 流水线封装（含中文 Windows UTF-8 兼容补丁）
main.py        # PySide6 界面
```

## 已知适配

- **中文 Windows 编码补丁**：skill 原版 `load_pack` 用默认编码读文件，GBK 环境读 UTF-8
  `pack.json` 会崩；`core.load_sticker` 在运行时覆盖为显式 UTF-8，不改 skill 源文件。
- **火山方舟（豆包/Seedream）适配**：base_url 填方舟入口即可（标准 `…/api/v3` 或 Coding 套餐
  `…/api/plan/v3` 都能用，粘成完整接口地址也会自动容错），自动改走方舟 JSON 接口
  `images/generations`，尺寸自动映射 2K、关闭水印；模型输出无透明通道时自动洪泛抠底。
  方舟按张计费（实际花费看火山账单），工具里的美元估算按 0 记。套餐入口只能调套餐内模型
  （如 `doubao-seedream-5.0-pro`），报 UnsupportedModel 说明该模型不在套餐范围内。
- **模型可自选**：设置分「图片生成模型」和「文案对话模型」两组，各自独立 key/地址/模型
  （文案模型留空则沿用图片组），可下拉选也可手填任意模型 ID。
- **AI 写文案**：第②步填灵感提示（可空）→「✨ AI 生成整套文案」→ 自动填表并校验，
  人工过目修改后再保存；产物永远是 AI 起草、人拍板。
- **专辑（系列）模式**：「文件 → 专辑管理器…」。专辑 = `packs/` 下的分组目录 +
  `album.json`，一个系列多套共用一个形象：新建套自动复制专辑里最新的角色图、
  风格继承专辑设定；每套带状态标签（角色/文案/生成张数/合成）。散装项目不受影响。
- **抽象创意参谋**：第②步「💡 抽象创意参谋」→ 文案模型列 ~12 个利于传播的抽象梗
  选题（词/场景/传播理由），勾选后一键填入灵感提示，再交给「AI 生成整套文案」。
- **实时缩略图墙**：第③步每生成完一张立刻上墙（双击看大图），断点续跑自动铺已有图。
- 冒烟测试覆盖：skill 加载 / 项目创建 / 文案校验 / dry-run 拦截 / build 合成 / check 检查 /
  方舟路由分发 / GUI 实例化。

## 打包分发（Windows / macOS）

### 方式一：GitHub Actions 云端打包 + 自动挂 Release（推荐）

推一个 `v*` 标签即可，三平台（Windows exe / Mac arm64 / Mac Intel）自动构建并挂到 Release：

```bash
git tag v1.0.0
git push origin v1.0.0
```

几分钟后在仓库 **Releases** 页面下载：

- `表情包工坊-v1.0.0-win.exe` —— 双击即用
- `表情包工坊-v1.0.0-mac-arm64.zip` —— Apple Silicon（M 系列）
- `表情包工坊-v1.0.0-mac-intel.zip` —— Intel 芯片

Mac 安装：解压 → `表情包工坊.app` 拖进「应用程序」→ **右键 → 打开**（未签名，首次需右键绕过 Gatekeeper）。

普通 push 到 main / Actions 页面手动触发只出构建产物（Actions 的 Artifacts 区，90 天有效期），不建 Release。

### 方式二：本机打包

PyInstaller 不支持交叉编译，本机是什么平台就打什么包：

```bash
pip install PySide6 Pillow pyinstaller
python build_exe.py
```

- Windows 产物 `dist/表情包工坊.exe`（单文件）；macOS 产物 `dist/表情包工坊-mac.zip`（内含 .app）
- 首次运行生成 `config.json`（填 API Key/地址/模型）和 `packs/`（作品目录）；Mac 的数据在
  `~/Library/Application Support/StickerWorkshop/`
- skill 的 `sticker.py` 已内置进包，目标机器无需安装 ray-sticker-shop；skill 更新后重跑同步
- 从源码运行则照旧用「启动表情包工坊.bat」

## 合规提醒

只做你有权使用的形象：不做明星、影视动漫游戏角色、二创同人；未成年人照片不投稿（仅可家长私下自用）。
微信注册与提交须本人实名操作，过审由微信决定。
