# 给 AI 一台手机 · 交接说明

> **2026-10-20 接续说明：下文是 10 月 19 日的历史交接。最新修复、验证和产物以 CODE-REVIEW.md、VALIDATION.md 及 dist/1.0.0/SHA256SUMS.txt 为准。**
> 本轮保留版本和签名；隐私开关改为原生 switch + Android 确认结果，连接过渡可取消，修正了卡片/滚轮/定时器问题。旧产物哈希已失效。

> 目标读者：接手本项目的工程师或 Codex。
> 当前版本：**1.0.0（versionCode 1）**
> 代码根目录：`D:\BaiduNetdiskDownload\kira`，**不是 git 仓库**，没有提交历史，请先做一次本地备份。

---

## 1. 项目是什么

三部分组成，共用一条连接链路：

| 部分 | 路径 | 职责 |
|---|---|---|
| 手机 App | `uni-app/` | uni-app x（uvue）写的 Android App：连接设置、设备状态、动效开关、防截屏保护 |
| 原生桥 | `android-app/app/src/main/java/top/kira/phone/` | 无障碍服务、截图、控制指令、`PhoneRuntime`；UTS 模块 `uni-app/uni_modules/kira-phone/utssdk/app-android/` 是它的同步副本 |
| Python 插件 | `phone_control/` | KiraAI 插件：生成连接信息、通过 WebSocket 控制手机 |

版本号只有一个真源：仓库根 `release.json`。改完跑 `python scripts/sync_release.py --write`，会同步 `uni-app/manifest.json`、`android-app/app/build.gradle`、`phone_control/manifest.json`、UTS 包和 `release.xml`。

---

## 2. 这一轮到底改了什么

### 2.1 版本重置

- 从 1.3.1 重置为 **1.0.0 / versionCode 1**，旧发布包已移到 `.runtime/archive-dist/`，旧更新记录归档在 `.runtime/archive/CHANGELOG-history-1.3.x.md`。
- 因为 versionCode 回退，已装 1.3.x 的手机必须先卸载再装本版。

### 2.2 界面整体重做

- 删除原来的淡粉配色和左侧抽屉方案，改为**底部四页签**：设备 / 设置 / 偏好 / 关于。
- 当前视觉：**深蓝夜空渐变 + 星点 + 白卡**。
  - 背景：`.app` 上 `linear-gradient(to bottom, #071A33 0%, #0A2344 36%, #123F70 66%, #2F6FB2 100%)`，`App.uvue` 的 page 兜底 `#071A33`。
  - 星点：`.sky` 层里 34 颗 `.star`，坐标由 `(i*37+5)%96 / (i*61+7)%86` 生成，`starTwinkle` 每 2.6s 翻转透明度，逐颗 `delay = index*70ms`。
  - 强调色 `#1E63B4`，深底链接 `#8CC6FF`，标题 `#F4F8FF`，深底次级文字 `#93AACB`，白卡正文 `#555C62`。
  - 顶部标题、状态 chip、tabbar、抽屉全部反色为浅色。
- 设计规范收口：字号只有 11 / 14 / 18 / 26 四档，字重只有 400 / 600；间距全部落在 4/8 网格；主要触控目标 ≥44×44；卡片内边距 24。
- 关键文件：`uni-app/pages/index/index.uvue`（整页重写，含模板/脚本/样式）、`uni-app/App.uvue`、`uni-app/components/{FeedbackButton,ProgressRing,SwipeDeck,SpeedWheel}.uvue`。

### 2.3 修掉的原始 bug

- **Android 上按钮没有文字**：原生 `<button>` 换成 `view + text` 自绘，勾号、等待动画独立绘制。
- **防截屏/录屏**：`PhoneRuntime.secure(Activity, boolean)` 控制 `FLAG_SECURE`，默认开启；`setRecentsScreenshotEnabled` 同步最近任务预览。
- **防截屏开关按不了**：去掉关闭前的 `uni.showModal`，改为直接翻转并调原生；`.switch` 与圆点各自 `@click.stop`，`.shield-row` 加 `position: relative` 给涟漪做锚点。关闭时用 toast 提示。

### 2.4 动效清单（全部在 `index.uvue` 与四个组件里）

| 动效 | 位置 | 关键参数 |
|---|---|---|
| 完成反馈 | `FeedbackButton.uvue` | 胶囊收缩成 60px 圆（`#12805D`），勾号由 L 形边框画出，8 颗粒子迸发；成功态 900ms 后复位 |
| 进度环 | `ProgressRing.uvue` | 14 个点，点亮数 `round(value/total*14)`，数字条 `translateY(-roll*38)`，460ms easeOutCubic 滚动 |
| 叠卡展开 | `index.uvue` `stackStyle` | 展开 `top=i*100`、`scale=1`、延迟 `i*70ms`；收起 `top=i*9`、`scale=1-i*0.035`、延迟 `(2-i)*50ms` |
| 步骤卡滑动 | `SwipeDeck.uvue` | 拖拽跟手 + 速度液态形变（`lean`/`liquidX`/`liquidY`），松手磁吸 `ratio = target - distance*exp(-6.4p)*cos(1.5πp)`，460ms，越界阻力 0.3 |
| 惯性滚轮 | `SpeedWheel.uvue` | 56px/行，拖动时距刻度 <18px 吸入；松手速度投射 + 560ms 阻尼余弦吸附 |
| 页签流体胶囊 | `index.uvue` | 切换时 `scaleX 1.32` 保持 140ms，再 380ms `cubic-bezier(0.34,1.56,0.64,1)` 回落；相邻页签同时 `translateX(±3px) scale(0.94)` 让位 |
| 页签涟漪 | `index.uvue` `playReveal` | 半径 96px，`scale .22→1`、`op .9→0`、300ms；`pointer-events: none` |
| 手势换页 | `index.uvue` `.stage` | 横滑跟手，header 0.18× 反向视差；过 20% 宽或速度 0.5px/ms 才切页，否则 460ms 回弹 |
| 卡片展开 | `index.uvue` detail | 从卡片矩形 360ms 扩到全屏；下拉跟手缩小，>110px 或速度 0.65 关闭，否则 440ms 回弹 |
| 侧边菜单 | `index.uvue` drawer | 300px，320ms `cubic-bezier(0.22,1.12,0.36,1)`，条目 `delay = 60+i*36ms` 错开淡入 |
| 连接转场 | `index.uvue` `runHeroTransition` | 内容下沉淡出 190ms，横线扫过 560ms，换入「正在连接服务器」回弹 360ms |
| CTA 光环/柔光 | `index.uvue` + `FeedbackButton.uvue` | 呼吸 1600ms（op .4↔.9、scale 1↔1.025）；按下 0.97/110ms；扫光 40px、`rgba(255,255,255,.2)`、780ms、3.8s 周期 |
| 切设置页转场 | `index.uvue` `enterFromRight` | 未配置点「开始连接」→ 设置页从右侧 16% 位移、透明度 0.4，340ms 轻推淡入 |
| 勾选错峰 | `index.uvue` | 偏好列表勾号 `transitionDelay = index*40ms` |

所有动效都受「界面偏好」里的三个开关（完成反馈 / 卡片与连线 / 涟漪反馈）控制；关掉后功能不受影响。

---

## 3. 文件改动索引

新增：

- `UI-OUTLINE.md`：UI 大纲（信息架构、设计 token、逐页拆解、组件规格、验收清单）。
- `INTERACTION-SPEC.md`：按 Advanced Interaction Design 拆的交互动效规格（模式选择 + 英文可复制 prompt）。
- `HANDOFF.md`：本文件。

重写/大改：

- `uni-app/pages/index/index.uvue`：四个页面、tabbar、抽屉、滚轮 sheet、详情面板、星空层、所有动效状态与手势。
- `uni-app/components/FeedbackButton.uvue`：自绘按钮 + 成功动画 + 柔光。
- `uni-app/components/ProgressRing.uvue`、`SwipeDeck.uvue`、`SpeedWheel.uvue`。
- `uni-app/App.uvue`：页面底色。

小改：

- `uni-app/lib/phone.js`：网页适配器补 `secure()` / `setSecure()`，版本号默认值。
- `uni-app/uni_modules/kira-phone/utssdk/app-android/index.uts`、`interface.uts`：`secure()`、`setSecure(enabled)`、`reveal(duration,x,y)`。
- `android-app/app/src/main/java/top/kira/phone/PhoneRuntime.java`：`secure(Activity, boolean)`、`reveal(Activity,int,int,int)`。
- `release.json`、`uni-app/manifest.json`、`android-app/app/build.gradle`、`phone_control/manifest.json`、`release.xml`：版本 1.0.0 / 1。
- 文档：`CHANGELOG.md`、`README.md`、`新手使用说明.md`、`VALIDATION.md`、`DEVELOPMENT.md`、`uni-app/README.md`、`android-app/README.md`、`phone_control/README.md`。

原生同步规则：**只改 `android-app/app/src/main/java/top/kira/phone/` 下的 canonical Java**，再跑 `python scripts/sync_uni_native.py --write` 同步到 UTS 模块，不要反向改副本。

---

## 4. 构建 / 预览 / 打包

```powershell
# 网页预览
python scripts\compile_uni.py --hbuilderx .runtime\hbuilderx\HBuilderX --platform web
# 产物：uni-app\unpackage\dist\build\web

# Android 资源
python scripts\compile_uni.py --hbuilderx .runtime\hbuilderx\HBuilderX --platform android
# 产物：uni-app\unpackage\resources\app-android

# Gradle 出未签名 APK
$env:JAVA_HOME="D:\BaiduNetdiskDownload\kira\.runtime\jdk21\jdk-21.0.12.1+1"
$env:ANDROID_HOME="D:\BaiduNetdiskDownload\kira\.runtime\android-sdk"
$env:GRADLE_USER_HOME="D:\BaiduNetdiskDownload\kira\.runtime\gradle-home"
& .\.runtime\gradle-9.2.1\bin\gradle.bat --project-dir uni-app/native-android `
  -PuniSdkDir="D:/BaiduNetdiskDownload/kira/.runtime/uni-sdk/Android-uni-app-x-vapor-SDK@101163-5.26" `
  assembleRelease --console=plain

# 签名 + 校验 + 打包
$bt=".runtime\android-sdk\build-tools\36.0.0"
& "$bt\zipalign.exe" -p -f 4 uni-app\native-android\app\build\outputs\apk\release\app-release-unsigned.apk .runtime\GiveAIAPhone-1.0.0-aligned.apk
& "$bt\apksigner.bat" sign --ks .runtime\phone-debug.keystore --ks-key-alias androiddebugkey `
  --ks-pass pass:android --key-pass pass:android `
  --out .runtime\GiveAIAPhone-1.0.0.apk .runtime\GiveAIAPhone-1.0.0-aligned.apk
python scripts\verify_uni_apk.py .runtime\GiveAIAPhone-1.0.0.apk
python scripts\package_release.py --apk .runtime\GiveAIAPhone-1.0.0.apk
```

坑：

- uvue 的 `linear-gradient` **不接受 `180deg`**，必须写 `to bottom`，否则 Android 编译报 `Invalid linear-gradient value` 并只保留纯色。
- uvue 不支持后代选择器，状态样式要用修饰类（如 `.tab-label-on`）。
- H5 里 `.uni-scroll-view` 有两层，滚动要操作 `document.querySelectorAll('.uni-scroll-view')[1]`。
- 用 PowerShell 的 `python -c` 改文件时，字符串里的 `%`、括号、反斜杠容易被 PowerShell 解析，批量替换一律写成 `.py` 文件再执行。
- 本机只有调试 keystore（`.runtime/phone-debug.keystore`，alias `androiddebugkey`，口令 `android`），证书 SHA-256 `7fd2b4272f3adc796a7da832c10770caaf19f8a0e3750cc84b3a20551629943d`；正式发布应换固定私钥并保持与上一版一致。

---

## 5. 当前产物

`dist/1.0.0/`：

| 文件 | 大小 | SHA-256 |
|---|---|---|
| `GiveAIAPhone-1.0.0.apk` | 76,366,274 | `bdbd93a9406d4b2307875bbbc49a1574914d362e7ab7cf8213f1511eeafc31b6` |
| `phone_control-1.0.0.zip` | 33,895,239 | `01df7653e3eed01b330b66d830bc9916f20e62313883d8554fb02978cd5d7a4e` |
| `give-ai-a-phone-1.0.0-source.zip` | 163,756 | `594a8d7160b86a1ef31ed9e55aab5d2c5f824440cae3a01d037ad4999da27c4d` |

APK 已用上面那把调试密钥签名（v2/v3 通过），`verify_uni_apk.py` 报告 14809 个 DEX 类，`aapt2` 显示 `versionCode 1 / versionName 1.0.0 / label 给 AI 一台手机`。插件 ZIP 里内嵌的是同一个 APK。

---

## 6. 验证到什么程度

已验证（网页 390×844，CDP 逐页 + DOM 探针）：

- 四个页签、侧边菜单（滑入 / 条目错开 / 点遮罩关闭）、详情面板（展开 / 下拉缩回 / 关闭按钮）。
- 步骤卡拖动吸附、滚轮惯性吸附、时间线逐段填充、叠卡展开/收起。
- 勾选错峰 `0s / 0.04s / 0.08s`；页签让位 `matrix(0.954…)`；开关涟漪可见；成功勾号 + 粒子。
- 渐变 computed 值、星空层、文字对比度（AA）。
- `node --test scripts/test_ui_interactions.mjs` 3 通过；`test_android_gate.py` CommandGate 5 + ServerAddress 26 通过；`sync_release.py`、`sync_uni_native.py` 通过。

**没验证的**：

- 真机（Android 8–16）上的观感与手感、关闭防截屏后系统截图是否真能拍到、无障碍与连接链路。
- `pytest` 本机缺模块，Python 测试子集未跑。
- AOCI 索引（`aoci.txt`）在本会话没有 MCP 工具可用，未维护；接手后请按 AGENTS.md 跑 `aoci_maintain`。

---

## 7. 交给 Codex 的审查任务

不改 UI、不改交互参数，先做**全量代码审查**，按 P0 / P1 / P2 输出到 `CODE-REVIEW.md`：

1. `index.uvue` 的动效状态机是否有竞态（timer 未清、重复触发、页面切换时状态残留）。
2. 手势换页与 `SwipeDeck` / 详情面板的触摸冲突边界。
3. 星空层与绝对定位层是否影响点击命中。
4. `PhoneRuntime.secure(Activity, boolean)` 的线程与异常路径；关闭保护后是否真的 `clearFlags`。
5. UTS 与 Java 副本是否一致（`sync_uni_native.py`）。
6. 版本号单一真源是否还有漏网字符串。
7. `package_release.py` 产物的 SHA 自校验是否覆盖全部文件。
8. 深色主题下的对比度回归（新增文字是否还在 AA 以上）。

**不要动**：动效参数、配色 token、文案、`release.json` 版本号、签名证书。

---

## 8. 快速索引

| 想改什么 | 看哪里 |
|---|---|
| 页面结构 / 文案 | `uni-app/pages/index/index.uvue` 模板段 |
| 动效参数 | 同文件 `<script setup>` 里的 ref/computed + 四个组件 |
| 颜色 | 同文件 `<style>` 末尾的 token 区 |
| 原生能力 | `android-app/app/src/main/java/top/kira/phone/` |
| 发布流程 | `DEVELOPMENT.md`、`scripts/package_release.py` |
| UI 规范 | `UI-OUTLINE.md` |
| 交互动效规范 | `INTERACTION-SPEC.md` |
