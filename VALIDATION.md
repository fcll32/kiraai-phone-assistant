# 1.0.0 版本重置验证 · 2026-10-27

- 保留 1.1.9 功能代码，`release.json` 的版本名/版本码重置为 **1.0.0 / 1**，协议 1、包名 `top.kira.phone` 和原签名不变。
- uni-app Android 资源编译通过，Gradle `assembleRelease` 成功；APK 14,938 个 DEX 类，`scripts/verify_uni_apk.py` 通过官方弹窗、控制桥、服务与资源检查。
- Build Tools 36.0.0 的 `zipalign -P 16`、`apksigner` v2/v3 签名和证书检查通过；证书 SHA-256 仍为 `7fd2b4272f3adc796a7da832c10770caaf19f8a0e3750cc84b3a20551629943d`。
- APK 76,484,661 字节，SHA-256 `a2670ac556e3ecf6690cc2078ec755d46cb42f3f0f05e6f475212b43f03b2e2c`；插件 `phone_control-1.0.0.zip` SHA-256 `7dbad04283a1176230cf5fd1bd108e391f6db87117f4d7847ac0509e6506d8c8`。
- `pytest scripts/test_release.py` 使用工作区独立临时目录运行，**6 passed**；首次在受限临时目录因 `.lock` 权限失败，改用授权构建环境后通过，不是业务失败。
- 发行目录 `dist/1.0.0/` 包含独立 APK、插件 ZIP、源码 ZIP、`1.0.0-改动说明.md`、新手说明和 6 个文件的 SHA-256 清单；旧 1.0.0–1.1.8 已归档，1.1.9 目录保留对照。
- 本版 versionCode 1 低于 1.1.9/code 11，已安装 1.1.9 的手机不能覆盖降级；需保存连接信息后卸载旧 App 再装。本轮未做真机安装、公网连接、通话和各厂商无障碍验收。

---

# 1.1.9 第二轮验证 · 2026-10-27

- KiraAI 3.1.0：`phone_control/tests scripts/test_release.py deploy` **162 passed**，含新增 6 项语音传输回归。首次在原实现运行新增故障复现，4 项明确失败后修正。
- KiraAI 3.0.1：内置服务与语音传输边界共 **35 passed**，日志 `.runtime/test-119-301-final.log`。
- Node 界面测试 **48 passed**，新增实验状态按需查询、进行中继续刷新和隐藏/重新显示验证。9 秒闲置期间减少 10 次实验状态读取，普通连接与通话状态不受影响。
- `android-app/tests/run_socket_regressions.py` 本地运行通过：使用 JDK 生成临时证书，执行实际 SocketSecurity 的 TLS 指纹、主机名、有效期及握手停止检查。临时证书自动清理，CI 已接入但未在 GitHub 执行。
- uni-app Android 编译通过，Gradle release 成功；APK 14,938 个 DEX 类、官方弹窗、16 KiB 对齐及 v2/v3 签名检查通过。名称 KiraAI 手机助手，1.1.9 / code 11，minSDK 26、targetSDK 35，沿用原签名。
- 日志：`.runtime/test-119-before.log`、`test-119-final.log`、`ui-119.log`、`compile-119.log`、`build-119.log`。

本轮未做真机安装、帧率/功耗/公网延迟、真实模型和 QQ 收音验收；发送失败测试中的 WebSocket 边界受控，已有实际 TLS/Kira Agent/SQLite 链路仍参与回归。功能和后续方案见 `1.1.9-改动说明.md`。

---

# 1.1.8 效率优化验证 · 2026-10-27

- KiraAI 3.1.0：插件、部署及发行测试 **156 passed**；3.0.1 内置服务兼容测试 **29 passed**。仅有依赖 Authlib 弃用提示。
- 新增 7 项回归验证 UI 操作链、截图回退、会话隔离、无效模式拒绝、图片编码复用、缓存字节上限和应用刷新能力协商。
- 受控测试中，5 次 UI 点击后的截图请求为 0；同时发图和识图只编码一次；16 个 8 MiB 合成图片只缓存最新 4 个。此上限不等于进程总内存。
- Node 交互/组件 **46 passed**；原有 JVM **233 checks passed**；新增 AppCatalog 测试验证 20 次读取只加载一次、15 秒过期、强制刷新、只读快照与加载失败行为。
- Android 实际方法边界回归通过：保留通话中启动控制、禁止运行时改配置、单轮语音错误恢复和旧轮错误丢弃。
- JVM 真实 TLS 验证正确指纹通过，错误指纹、错误主机名和过期证书拒绝；真实 Java-WebSocket 卡住握手后的关闭回归通过。
- uni-app Android 编译和 Gradle release 构建成功；APK 包内 14,938 个 DEX 类检查通过，含桥接、服务及官方弹窗。
- APK：KiraAI 手机助手，1.1.8 / versionCode 10；minSDK 26、targetSDK 35；16 KiB 对齐，v2/v3 签名通过，沿用原签名和安装身份。

日志：`.runtime/test-118-first.log`、`test-118-301.log`、`ui-118.log`、`compile-118.log`、`build-118.log`。原生证书与握手测试为本地 JVM 环境；未执行 Android 真机安装、帧率/延迟测量、真实模型及 QQ 投递验收。详细审查范围和后续方案见 `1.1.8-改动说明.md`。

---

# 1.1.6 验证记录 · 2026-10-26

- KiraAI 3.1.0：`pytest phone_control/tests scripts/test_release.py deploy` **139 passed**。实际安装插件 ZIP、管理接口登录保护、首次保存不监听、8 位密码真实 TLS 认证、停止断开和端口释放、重载恢复及配置落盘均已运行。
- KiraAI 3.0.1：内置服务套件 **29 passed**，含同一启停和短密码链路。
- Node 界面逻辑测试 **46 passed**，新增引导跳转、连点、禁动效、隐藏、跳过和重看；原生接口在这些测试中模拟。
- JVM **233 checks passed**，含新增密码策略 14 项，两端接受规则一致。
- uni-app Android 资源编译通过，无本次新增 CSS 警告；Gradle release 构建成功。已修正新引导中 Android 不支持的 gap。
- APK DEX 检查通过：14,936 类，包含原生桥、控制／通话服务和官方弹窗模块；名称 KiraAI 手机助手，1.1.6 / code 8，minSDK 26、targetSDK 35。
- APK 已用原有签名签署并验证 v2/v3，16 KiB 对齐；安装身份不变。
- 浏览器实际点击了引导第一步和“去填写连接信息”，确认显示第二步并进入设置页；390×844 DOM 边界下弹窗宽 390、高 600，没有越出视口。浏览器截图工具异常，未形成完整视觉验收或真机帧率证据。

未执行：Android 真机安装、真实公网手机控制、真实 QQ 投递、麦克风收音和动画帧率测量。全量人工审查按用户要求暂停；以上通过的是本次范围及现有自动回归，不意味着所有代码无 Bug。

测试日志保留在 `.runtime/test-116-final.log`、`test-116-301.log`、`ui-116-second.log`、`java-116.log`、`compile-116-final.log`、`build-116-final.log` 和 `apk-116-signature.log`（本地文件，不打进发布包）。

---

# 1.1.5 连接失败原因与自动重试修复检查

## QQ 图片发送修订（2026-10-26）

- 根因：插件以 `image` 判断图片能力，Kira 的 QQ/NapCat 和 QQ 官方适配器声明的却是 `img`。截图上下文不经过发送判断，因此出现 AI 能看图、QQ 发图被拒的差异。
- `_send` 兼容 `img` 与 `image`，保留纯文字适配器拒绝、发送失败回报及会话权限。修复前新回归明确失败，修复后覆盖两种 QQ 能力、`send_to_chat=true`、已有截图转发及实际 OneBot base64 图片段生成。
- 安装真实插件 ZIP 后，以 QQ 的真实能力列表运行 TLS 手机模拟端与 Kira Agent/Provider；同时检查发送接口被调用和图片进入下一轮模型请求。聊天发送接口及手机、模型为模拟，不等于真实 QQ 投递验收。APK 未改动。
- Kira 3.1.0：50 项发送、工具、TLS 与 ZIP 安装检查通过；Kira 3.0.1：4 项图片发送兼容检查通过。旧的 `image` 能力名称、文字聊天拒绝图片、发送失败反馈均有回归覆盖。

## 后续公网 TLS 排障（2026-10-25）

- 已从公网复现错误入口：8443 返回明文 Uvicorn HTTP，TLS 握手超时。用户提供的 Docker inspect 确认宿主机 5267、8443 均映射到容器 5267。用户改为各自同号映射并重建后，公网 TLS 1.3、TLS 1.2 握手及设备路径 WebSocket 101/accept 校验均成功。
- 公网探测仅检查传输与入口，未发送密码或手机命令，不证明最终手机认证、无障碍动作或真实模型效果。探测读取公开证书时未验证信任，不改变 App 的证书校验；App 继续使用配对校验码。
- 修正 ConnectionFailure 的错误分类及重试策略：未知 TLS 和临时握手中断可重试，证书、指纹等明确配置错误仍停止；提示包含真实异常类型与原因。增加 15 项断言，先观察失败，再修正通过。
- 本轮通过：ConnectionFailure 33 项；JVM 共 219 项；Node 43 项；真实 TLS 服务、ZIP 安装与发行相关 Python 20 项。没有重新执行全量插件审查。
- Android 页面与原生 APK 构建通过；14935 个 DEX 类、v2/v3 签名通过，同签名可覆盖安装。此次 APK SHA-256：`7bd5b02319bfb5bf77fc6ac46c527ce2531895487786bc219f6b03d087a6c523`。

## 此前修订记录

日期：2026-10-25。App / 插件 1.1.5，versionCode 7，协议与签名沿用。

- 修复 `ConnectionService.onError` 把所有异常固定显示为“网络错误”的问题。新增 `ConnectionFailure` 将校验码不一致、证书过期、域名不匹配、连接超时、端口拒绝、DNS 失败、服务器 503、已有手机在线、服务器关闭握手和非法配置分别显示为可操作的中文原因。
- 指纹、证书、域名和配置错误会停止重试并保留原因，避免无意义循环；超时、拒绝、DNS、503、`socket closed` 等临时故障会立即关闭旧连接并按 1 至 30 秒退避重试。服务端 `1013` 提示已有手机在线，`1008` 仍提示密码或设备不匹配。
- 修复主动关闭 socket 触发第二次 `Socket closed` 回调、覆盖首次真实错误的问题：`PhoneSocket.closing` 在关闭前置位，后续 `onError` 忽略本地关闭回调。`socket closed` 单独提示服务器在连接建立时关闭并自动重试。
- 修复端口已接受 TCP 但 TLS/WebSocket 握手无响应时无限停在“正在连接”的问题：Java-WebSocket 的 15 秒连接超时只覆盖 TCP 建连，新增 20 秒握手看门狗；超时后关闭半开连接、保留最近失败原因并继续重试，不再永久卡住。
- 用与 App 相同的 Java-WebSocket 1.5.7、自定义指纹 TrustManager 和 HTTPS 主机名校验连接本地 `phone_control.server` 的 `wss://127.0.0.1:18443/ws/plugin/phone_control/device`，成功完成 TLS、WebSocket Upgrade、hello 和 welcome；证明客户端证书指纹与协议链路本身可用，公网若仍出现握手超时，应继续检查端口映射是否真正到达该监听。
- HBuilderX 5.26 页面资源编译和 Gradle `assembleRelease` 成功；新增 Java 分类器及移植后的 UTS 原生文件已同步，`sync_uni_native.py` 检查 16 个文件一致。手动 Java 门禁的 `ConnectionFailureTest` 18 项断言通过；沙箱临时目录无法创建包目录，自动门禁脚本因此失败，属环境限制。
- 43 条 Node 界面交互/回归通过。APK 16 KiB 页对齐、v2/v3 签名及 14935 个 DEX 类检查通过，`_uni-modal` 和 `ConnectionFailure` 均在包内；`socket closed` 与握手超时中文提示已确认编入 DEX。
- 原证书 SHA-256：`7fd2b4272f3adc796a7da832c10770caaf19f8a0e3750cc84b3a20551629943d`，可覆盖安装。签名后 APK 共 76,476,084 字节，SHA-256：`a87cd3f2145efc8085990a54d238de3012bc421822485a57bf2f82b3204be6b7`。
- 本机未连接 Android 真机；仍需用户覆盖安装后实测。若是旧公网 IP 或服务器重建过证书，应按 App 提示回插件页重新复制三要素，旧校验码无法继续通过证书校验。

---

# 1.1.5 空白连接输入与 `_uni-modal` 安装包修复检查

日期：2026-10-25。App / 插件 1.1.5，versionCode 7，协议与签名沿用。

- 开始连接时在调用原生保存前检查空白服务器地址和密码，分别提示“请填写服务器地址，例如 203.0.113.10:8443”“请填写连接密码”。不打开连接确认、不启动服务、不清空输入；原生格式和密码校验仍保留。
- HBuilderX 5.26 页面编译及 Gradle assembleRelease 成功；首次构建遗漏项目 `GRADLE_USER_HOME` 导致 native-platform 加载失败，使用已有项目缓存后成功。APK 内 `app-service.js` 已确认包含上述两条提示。
- 43 条 Node 界面回归通过（新增空白地址/密码场景）；3 项无需临时目录的发行检查、元数据及原生同步检查通过。APK 16 KiB 页对齐、v2/v3 签名和 14933 个 DEX 类检查通过，仍含 `_uni-modal` 运行时。
- 原证书 SHA-256：`7fd2b4272f3adc796a7da832c10770caaf19f8a0e3750cc84b3a20551629943d`，可覆盖安装。最终 APK 共 76,476,084 字节，SHA-256：`2f5be4b85bba8ac174b04ac65e6d3b8e22c60a7b10805583612cd1ed39f64c7d`。
- 受限模式的管道/子进程编译日志见 `.runtime/compile-115-blank-input.log`；获准运行的官方编译和正式 Gradle 构建成功，输出由后台任务返回。本机未连接 Android 真机，需用户实测空白输入提示及正常连接确认。

---

# 1.1.5 `_uni-modal` 安装包修复检查（上一修订）

日期：2026-10-25。App / 插件 1.1.5，versionCode 7，协议与签名沿用。

- 旧 APK 的 DEX 中缺少 `_uni-modal` 提供方，但页面调用了 `uni.showModal`；离线工程此前只声明 `uni-prompt-release.aar`。补入同版本官方 SDK 的 `uni-modal-release.aar`，不是修改业务页面绕过确认，也不是改用自定义基座。
- `assembleRelease` 成功，自动注册表包含 `IoDcloudUtsUniModalAutoRegister`。本次仅改变原生依赖，沿用已编译的页面资源；页面编译器受当前 Windows 沙箱的子进程限制未能重跑。
- 修复后 APK 已做 16 KiB 页对齐，v2/v3 签名验证通过；`verify_uni_apk.py` 检查 14933 个 DEX 类，包含弹窗实现、方法注册及自动注册类。旧 APK 用新增校验按预期失败。
- 包名 `top.kira.phone`，versionCode 7 / versionName 1.1.5，minSdk 26 / targetSdk 35。APK 共 76,476,084 字节，SHA-256：`6d6788c2fcded183850581c691bab2433e09f0f2b481cbd8ef3c2b799d19ef8b`。证书 SHA-256：`7fd2b4272f3adc796a7da832c10770caaf19f8a0e3750cc84b3a20551629943d`，与旧 APK 相同，可覆盖安装。
- 42 条 Node 界面回归通过；3 项无需临时目录的发行源码检查通过，实际发行脚本和 APK 校验通过。Pytest 另有 3 个依赖临时目录的用例被当前沙箱拒绝访问，并非业务断言失败。本机未连接 Android 真机，仍需用户覆盖安装后点击“开始连接”，确认弹窗出现且取消不会启动连接。
- 构建与签名日志：`.runtime/build-115-modal.log`、`.runtime/sign-115-modal.log`、`.runtime/package-115-modal.log`。权限诊断报告：`.runtime/acl-recovery/acl-report-4a303cdc778947f8b63455a6ead77b41.jsonl`，未修改文件权限。

以下为首次 1.1.5 构建记录，旧 APK 哈希已失效。

---

# 1.1.5 连接流程检查

日期：2026-10-25。App / 插件 1.1.5，versionCode 7，协议与签名沿用。

- 用户反馈开启无障碍后点击连接完全没有确认弹窗。移除按钮透明点击覆盖层，改由按钮本体接收点击并隔离页面横滑手势；尚无真机点击证据，不能断言该层就是用户设备上的唯一原因。
- 修复可复现的草稿被页面导航覆盖、弹窗同步失败后确认锁不释放、切后台后旧弹窗回调失效问题；输入错误和权限未就绪在按钮下方显示。连接时先保存当前输入，必须确认后才启动服务。
- 新增 5 条界面回归，修改前 5 条失败，修复后全部通过；加上既有检查，共 42 条 Node 测试通过。
- 原生服务重复启动时不再覆盖已连接状态；Android 编译与 Gradle assembleRelease 通过。此分支经代码检查，未用真机重复点击验证。
- 对 KiraAI 3.1.0 运行全部插件、部署与发行检查：122 passed。含真实 TLS 认证、错误密码、心跳、断线清理、重连身份变更、配置保存重载，以及实际无 APK ZIP 安装与管理 API。修正上一轮遗留的测试调用 build_plugin(apk=...)；APK 路由缺失时提示单独下载。
- JVM 检查 186 项通过：命令门控 5、地址解析 26、VAD 145、信号检测 10。
- APK 16 KiB 页对齐、v2/v3 签名、14904 个 DEX 类与页面及原生桥资源检查通过。APK SHA-256：`64156821fab8110f53c6080de52ac0d457a15dd8d8e39ff532794d8952c57755`。
- 签名证书 SHA-256：`7fd2b4272f3adc796a7da832c10770caaf19f8a0e3750cc84b3a20551629943d`。同签名 1.1.4 可覆盖更新。
- 日志：`.runtime/connection-before.log`、`connection-after.log`、`test-115-full.log`、`jvm-115.log`、`compile-115.log`、`build-115.log`、`sign-115.log`。

本机没有连接 Android 真机或用户公网服务器，UI 回归使用模拟原生桥，不能证明真实触摸命中、厂商权限行为、帧率或公网延迟。用户应安装 1.1.5 APK 验证原反馈路径；插件 ZIP 仍不含 APK。Python 首次发行测试因系统临时目录权限失败，改用工作区独立临时目录后通过；未更改系统权限。现有 Authlib 与 Gradle 弃用提示不阻断构建。

以下为历史记录。

---

# 1.1.4 插件安装包修订（2026-10-25）

旧发行 ZIP 约 34 MB，但内嵌 APK 为 76,455,494 字节，超过 KiraAI 对单文件和解压总量的 50 MiB 限制。此前安装链路测试使用小型 APK，未覆盖真实发行体积；内嵌内容一致并不证明可被核心安装。

已移除插件包内 APK，改为独立分发，更新 CI、打包脚本和说明。首次移除 APK 时的插件 ZIP 为 49,587 字节，解压总量 129,755 字节。使用实际发行 ZIP 通过 KiraAI 3.1.0 的 install_from_zip 和 PluginManager 加载，8 个工具注册成功，apk_available=false，管理页存在。5 项发行检查通过。APK 字节和签名不变，无需重装手机端。SHA256SUMS 已重新生成。

以下为首次 1.1.4 构建的验证记录；“内嵌 APK”结论已由上述修订取代。

---

# 1.1.4 / KiraAI 3.1.0 兼容验证

日期：2026-10-25。App 与插件 1.1.4 / versionCode 6，沿用协议 1、安装身份与原签名。

- 使用用户提供的 `kira3.10/KiraAI-3.1.0.zip`，源码版本为 `v3.1.0`；CI 固定官方仓库同版本提交 `dd8996909966b7f3737622cbf533c77bd2c9ff11`。
- 3.1.0 完整插件、部署与发行检查：120 passed、2 skipped；两项为旧代理部署的 OpenSSL 检查，随后加入本机 Git 自带 OpenSSL 路径单独补跑，2 passed。合计 122 项通过。
- 3.0.1 兼容检查：115 passed、7 skipped，其中 5 项仅适用 3.1.0；另外 2 项为上述已独立补跑的 OpenSSL 检查。
- 37 项 Node 交互回归通过；JVM 检查 186 项通过（命令门控 5、地址 26、VAD 145、实验信号 10）。
- 新增实际媒体清理竞态、语音失败/取消后的释放、64 token 工具文字截断仍保留图片、新版组件详情 API，以及保存前读取原生忙碌状态的回归检查。
- 真实 TLS + Kira Agent/Provider + SQLite 两轮通话中，截图后立即运行框架媒体清理，图片仍能进入模型请求并保存到历史。测试中的手机、STT/TTS、模型回复是模拟；不证明真实模型理解效果或公网延迟。
- Android 页面编译、Gradle assembleRelease 成功；APK 的 16 KiB 页对齐、v2/v3 签名、14904 个 DEX 类及页面/桥接资源检查通过。
- APK SHA-256：`ef5c4f83d19650fc9e062575d0fe339f277b37a6c9ff3092c5b01dfc792f13c3`。
- 签名证书 SHA-256：`7fd2b4272f3adc796a7da832c10770caaf19f8a0e3750cc84b3a20551629943d`。
- 发行目录为 `dist/1.1.4/`，插件 ZIP 内嵌同一 APK；干净源码导出到 `kira-phone/`。旧版本目录保留。

复现时设置 `KIRAAI_ROOT` 指向对应核心目录，运行 `python -m pytest phone_control/tests deploy/test_setup_public_ip.py scripts/test_release.py -q`。使用包含 OpenSSL 的 PATH 可直接运行部署证书检查。详细日志保存在本机 `.runtime/test-31-final.log`、`test-301-114.log`、`test-114-openssl.log`、`test-ui-114.log`、`compile-114.log`、`build-114.log`。

已知边界：未在 Android 真机安装验证，未测帧率、耗电、真实公网和语音延迟。Windows 紧凑截图保护依赖 3.1.0 的内部媒体锁和计数，后续核心升级需重新验证；过深数据目录仍可能超过系统路径限制。现有 Authlib 弃用提示、Manifest 合并提示和 Gradle 弃用提示未阻断测试与构建。

以下为历史验证记录。

---

# 1.1.3 柔和配色与排版验证

日期：2026-10-24。版本 1.1.3 / versionCode 5，协议、安装身份与签名不变。

- 36 项 Node 交互回归、5 项 Python 发布检查通过；更新连接卡标题的断言，其余连接、隐私和动效取消检查保留。
- Web、Android 页面编译和 Gradle assembleRelease 成功。
- 浏览器 390×844 检查首页正反面、连接表单、偏好、速度弹窗开关和通话页；320×844 检查主卡正反面。缩短主卡状态标题，减少窄屏换行。
- 本地截图：`.runtime/soft-home.png`、`soft-home-320.png`、`soft-back.png`、`soft-settings.png`、`soft-preferences.png`、`soft-call.png`。网页预览提示仅用于 Web，不代表手机连接结果。
- APK 已做 16 KiB 页对齐，v2/v3 签名验证通过，14904 个 DEX 类及页面、控制和音频桥资源验证通过。
- APK 大小 76,455,494 字节，SHA-256：`0bb356fa659f43478e4d7e5b0e82c7edcb89f6edbee1ff130fcf20c0b64be9a1`。
- 签名证书 SHA-256：`7fd2b4272f3adc796a7da832c10770caaf19f8a0e3750cc84b3a20551629943d`。
- 发行目录 `dist/1.1.3/`，保留 `dist/1.1.2/` 方便对比。

本轮主要调整配色、布局和短标题，保留已有交互与原生控制、通话实现；没有新增装饰循环或逐帧布局动画。尚未在 Android 真机安装测量帧率、内存和长期阅读舒适度，浏览器检查不能证明所有手机均不卡。Web 编译仍有既有动态 JavaScript 类型警告。

以下是历史验证记录，不计入本次重新执行的检查。

---

# 1.1.2 动效与排版验证

日期：2026-10-24。版本 1.1.2 / versionCode 4，控制协议与签名不变。

## 本次结果

- 36 项 Node 检查通过。新增连接主卡分段翻面、重复点击、隐藏与卸载取消、三档速度、弹窗父页事件数量、转写数组复用、详情打开等待与关闭复位检查；原权限和连接回归仍通过。
- 弹窗标准速度自动展开时，向父页发送 progress 的次数由逐帧发送改为 1 次；手势拖动仍发送位置。该结果是状态更新计数，不是 FPS 测量。
- 5 项 Python 发布检查通过。Web 与 Android 编译成功，Gradle assembleRelease 成功。
- 390×844 浏览器检查首页正反面、持续可见的连接按钮、连接表单、准备卡详情打开与关闭。截图位于本地 .runtime/perf-home.png 与 perf-hero-back.png，网页提示“网页界面预览”不会出现在真机正常连接状态中。
- APK 16 KiB 页对齐，v2/v3 签名验证通过，14904 个 DEX 类及页面/控制/音频桥资源检查通过。
- APK 大小 76,455,494 字节，SHA-256：`a3a4f7c00db423ff7b34a8e913f2086bb571bc70ddc4c19d1627fb26fb6e2daa`。
- 签名证书 SHA-256：`7fd2b4272f3adc796a7da832c10770caaf19f8a0e3750cc84b3a20551629943d`。
- 交付位置 `dist/1.1.2/`，插件 ZIP 内嵌同一个 APK。

## 本轮减少的开销

连接主卡用有限次状态更新和 transform 过渡，提前创建两面；能力卡不再中途创建另一面或插值阴影。详情提前创建，去掉滚动模糊；步骤标签不再逐帧改变字重；叠卡保留位移动效但不逐帧修改容器高度。首页装饰不再使用星光和呼吸常驻计时器，进度线使用缩放，未变化的转写数组不会被轮询替换。标准速度点准备卡的等待从 400ms 缩短到 100ms。

## 验证边界

本轮只调整界面与版本资料，没有修改原生控制、语音和服务器实现。没有在 Android 真机或模拟器上安装运行，也没有取得真机帧耗时、掉帧或内存数据；不能承诺所有手机都不卡。Web 编译仍有既有动态 JavaScript 类型警告。浏览器预览与模拟时钟检查不能替代真机手势和帧率验收。建议重点实测快速切页、翻面中切后台、低端机连续展开/关闭详情及调速。

以下是此前版本的历史记录，不计入本次重新执行的检查。

---

# 1.1.1 界面验证记录

日期：2026-10-23。版本 1.1.1 / versionCode 3，协议、安装身份与签名不变。

## 本次实际完成

- 31 项 Node 回归测试通过：原有权限、隐私、连接、通话测试仍通过；新增快速导航重定向、果冻开关等待原生确认、弹窗关闭后重开和过期甩动、翻面按钮门控、滑卡延时取消、浮动标签与吸顶吸附。
- 5 项 Python 发布测试通过：元数据一致、ZIP 内容、APK 原样内嵌、源码排除与文件校验清单。
- HBuilderX 5.26 Android 和 Web 编译通过；JDK 21 / Gradle 9.2.1 完成 assembleRelease。
- 390×844 浏览器预览确认四项导航、浮动输入框、背景缩至 0.92 的底部弹窗、连接详情。发现短详情滚动范围不足后已修复，实际滚动验证标题最终位于顶部（translateY -172px、scale 0.62）。
- APK 16 KiB 对齐后签名，v2/v3 验证通过；检查 14904 个 DEX 类及页面资源。
- APK 大小：76,451,001 字节。SHA-256：`858646bffb11f4a85ddb801fb04f46a91c17a5c2271dd109fb39fab57361db09`。
- 签名证书 SHA-256：`7fd2b4272f3adc796a7da832c10770caaf19f8a0e3750cc84b3a20551629943d`。
- 发行文件位于 `dist/1.1.1/`；插件 ZIP 内含同一个 APK。

## 验证边界

本轮修改界面与发布资料，未改手机控制或音频服务。下面的 117 项 Python 和 186 项 JVM 是 1.1.0 的基线记录，本轮没有重复宣称重跑。浏览器只验证排版及可观察交互；Android 8–16 真机触摸、低端机帧率、后台连接、截图保护和通话仍需实测。Web 编译保留动态 JavaScript 类型警告，Android 编译通过。3D 旋转在 Android 使用原生 rotateX/rotateY，Web 补充 perspective；视觉投影可能有平台差异。

---

# 1.1.0 历史基线记录

日期：2026-10-23。App 版本 1.1.0 / versionCode 2，应用 ID `top.kira.phone`，插件 ID `phone_control`，控制协议 1。此前修复见 [CODE-REVIEW.md](CODE-REVIEW.md)，通话范围见 [VOICE-PLAN.md](VOICE-PLAN.md)。

## 自动检查

- **117 项 Python 测试通过，无跳过**，20.17 秒。KiraAI 源码提交 `d5779b8157380d5ba58a22ba21763aa8b86241b4`。含插件 ZIP 安装、管理页认证、设备主动 TLS 连接、图片上下文和语音连接。补充的通话开关保存/重载与非法值拒绝测试单独通过。
- 语音测试使用真实 Kira AgentExecutor、FuncToolManager、OpenAI Provider/SDK、SQLite SessionManager 和两条真实 TLS 连接；手机与 STT、LLM、TTS 回复由模拟端提供。两轮测试证明截图工具结果和图片引用进入后续模型请求，并在重新创建会话管理器后恢复。
- 验证断线、重复音频编号、音频限额、错误密码、关闭通话开关、指定设备、并发通话拒绝、打断撤销授权、STT 忽略取消后的旧回复丢弃、等待设备锁期间换机拒绝。
- **24 项 Node 测试通过**：实际 uvue 脚本配模拟原生桥和时钟，覆盖隐私、连接、滑卡、滚轮、速度设置，以及麦克风授权不自动拨号、通话失败、通话与实验互斥、挂断、退后台和叠卡入口。
- **186 项 JVM 检查通过**：CommandGate 5、ServerAddress 26、VoiceVad 145、VirtualMicSignal 10。信号检测包括噪声、延迟、反相、静音、普通单音和不完整信号，不能代替真实音频路由验证。
- 版本与原生同步检查通过。新增原生类由 canonical Java 同步到 UTS，不单独维护副本。

## APK 与界面

HBuilderX 5.26 Android 资源编译成功；JDK 21、Gradle 9.2.1、Vapor SDK 5.26 完成 `assembleRelease`。首次编译发现公开 SDK 不包含 AudioManager.SUCCESS，已按 AOSP 返回码修正。仍有 Gradle 弃用、SDK platform-tools 许可提示及 Java 过时 API 提示；这些没有阻止本次构建。

APK 经过 16 KiB 页对齐和原开发密钥签名，v2/v3 验证通过。校验解析 **14904 个 DEX 类**，确认语音服务、虚拟麦克风、Shizuku provider、UTS 自动注册及首页资源存在。APK 共 **76,424,085 字节**，最低 Android 8、targetSdk 35，包含 arm64-v8a 与 armeabi-v7a。文件大小不是运行内存占用。

- 签名证书 SHA-256：`7fd2b4272f3adc796a7da832c10770caaf19f8a0e3750cc84b3a20551629943d`
- APK SHA-256：`c083c9f8a75790c72d6d42462a38bb4cdccf96dff6ee567c75efa078ffe86926`
- 交付文件校验清单：`dist/1.1.0/SHA256SUMS.txt`

本轮网页预览检查了 390×844 下的通话页、按钮文字与实验卡展开排版。网页仅预览，不访问真实麦克风；网页编译对既有 JavaScript 动态类型和生命周期导入有类型警告。后续改动包含状态条区分通话状态和动效速度，已通过 Android 编译及脚本测试。浏览器预览不证明 Android 触摸、窗口保护或帧率。

## 已修复的原生风险

- 打断时使用发送代次和锁，丢弃已经取出队列但尚未发送的旧音频。
- 挂断后，在旧 Service 销毁前拒绝立即复用，避免新通话继承旧关闭状态。
- 播放时暂停采麦；服务器提前发来 listening 状态也不会提前收音。
- 清理挂断时待播放的临时文件、播放器、录音、队列和音频焦点。
- 连接配置在通话/实验进行时禁止修改；用户授权麦克风不会自动启动录音。

## 仍需真机验证

本次没有在手机或模拟器安装运行，没有连接实际公网服务器或付费模型，不能声称 QQ/微信可用或承诺实际延迟。Shizuku 实验仅短测试信号；真实 shell 权限、厂商隐藏 API、音频路由及本机收音匹配均需实测。当前没有将 AI 回复持续注入第三方通话。

按新手说明先测试普通 App 通话，再测试通话中观察/操作手机、静音/打断/挂断、网络切换、后台/锁屏、其他来电抢占。随后分别测试 Shizuku 本机信号与 QQ/微信人工接收，记录型号、系统、应用版本及端到端延迟。蓝牙耳机、长期内存、低端机帧率及 Android 8–16 全版本尚未验收。GitHub Actions 未推送触发。

从原签名 1.0.0 可覆盖升级；历史 1.3.x 的版本码更高，仍需先保存设置再卸载重装。
# 1.1.7 · 2026-10-26 验证补充

- KiraAI 3.1.0 全套插件、部署与打包测试：149 passed；KiraAI 3.0.1 内置服务兼容检查：29 passed。
- UI 交互和组件回归：46 passed；原有 JVM 纯逻辑：233 checks passed。
- 新增原样生产方法边界回归：通话与控制双启动顺序、运行中配置修改拒绝、无效配置拒绝、单轮/旧轮/打断/认证/协议语音错误。
- 使用真实 Java-WebSocket 1.5.7 与本地不响应 TLS 的 TCP 服务，验证 SocketSecurity.closeNow 关闭底层连接并结束读取线程。测试为 android-app/tests/SocketStopTest.java。
- UI 控件观察能作为点击依据，跨会话拒绝；截图附带控件时仍保留图片上下文；旧 APK 提示升级；应用列表查询和按包名打开经过真实 WebSocket 路由测试，手机响应为模拟。
- Android 编译和 Gradle assembleRelease 成功；APK 含 14936 个 DEX 类，通过桥接和弹窗模块检查；versionName 1.1.7、versionCode 9、minSdk 26、targetSdk 35，v2/v3 签名与 1.1.6 相同。
- 未进行 Android 真机安装、动画帧率、真实模型、真实 QQ/NapCat 到达与厂商应用列表差异验收。不要将 JVM 边界替身或浏览器组件测试称为真机验证。

