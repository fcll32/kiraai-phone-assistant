# 开发与构建

普通用户请先阅读 [新手使用说明](新手使用说明.md)。本文件保留开发者需要的技术细节。

## KiraAI 3.1.0 兼容点

当前验证目标为用户提供的 `kira3.10/KiraAI-3.1.0.zip`；官方 v3.1.0 对应提交 `dd8996909966b7f3737622cbf533c77bd2c9ff11`。CI 固定该提交。通过 `KIRAAI_ROOT` 指定框架源码目录运行插件测试。

自定义语音工作流未经过核心 IM workflow，因此 `KiraVoiceBackend.run` 自行进入 `session_media_scope`，覆盖 Agent 执行和 `update_memory`。3.0.1 无此接口时使用空上下文。普通聊天由核心工作流管理作用域。

Windows 长路径分支必须保留紧凑目录；3.1.0 没有公开的自定义路径保护 API，该分支明确依赖 `core.utils.media_refs` 的 `_media_lock`、`_current_media_scope`、`_protected_media_paths`，按同一锁更新保护计数。其他路径使用公开存储接口。升级核心时应重新运行 `test_kira31.py`；不能仅写文件而绕过清理锁。取消时等待线程完成再让作用域退出。过深的 Windows 安装路径仍可能超过系统限制，建议使用较短的数据目录。

工具文字由核心执行截断，图片继续通过 `ToolResult.media_refs` 传递。不要把 base64 放进文字，也不要为了保留文字而绕过用户配置的输出上限。过小的上限可能丢失定位所需信息；建议保持核心默认值。普通聊天可继续使用核心记忆插件；App 通话保持设备独立会话及手机工具白名单，不自动开放长期记忆或其他管理工具。

## 组件

- `phone_control/voice.py`：独立认证语音连接、音频限额、Kira STT/Agent/TTS 与隔离上下文。
- `android-app/.../VoiceCallService.java`：原生收音、VAD、播放、焦点与前台通知生命周期。
- `android-app/.../VirtualMicRuntime.java`：Shizuku 实验入口与本机信号验证，非全局声卡。
- `phone_control/main.py`：KiraAI 工具、会话授权、截图生命周期与发送结果。
- `phone_control/protocol.py`：共享参数校验、图片数据和协议版本。
- `phone_control/remote.py`：手机主动连接、认证、超时与断线清理。
- `phone_control/server.py`：内置 aiohttp TLS 服务、自动证书、持久连接密码；只暴露手机 WebSocket 路径。
- `phone_control/web/index.html`：KiraAI 已登录管理页，通过受保护 API 查看连接信息、保存设置、下载 APK。
- `phone_control/adb.py`：可选 ADB 模式；App 模式不需要系统安装 ADB。
- `uni-app/`：uni-app x 5.26 蒸汽模式界面，含 UTS 桥接和离线 Android 工程。
- `uni-app/native-android/`：独立桥接库参与 UTS 自动注册；minSdk 26、compileSdk 36、targetSdk 35。
- `android-app/`：控制服务的 Java 源码及旧界面；新版 APK 不使用旧 MainActivity。
- `deploy/`：保留的旧版手动 Nginx 方案，内置服务无需使用。

协议版本为 1，服务端路径为 `/ws/plugin/phone_control/device`。手机输入 `IP:端口` 后，`ServerAddress` 在本地补上 WSS 协议和此路径；不会改为明文连接。原完整 WSS 地址及自定义路径继续兼容。IPv6 简写使用 `[IPv6]:端口`。

APK 应用 ID 为 `top.kira.phone`，插件 ID 为 `phone_control`；升级时保持不变。SharedPreferences 中仍存完整 URL，配置字段名也保留，中文显示名称的变化不迁移或清空数据。

只有公网 IP 时使用包含 IP SAN 的自签证书。内置服务通过 cryptography 自动生成，requirements.txt 由 KiraAI 安装器处理，无需调用系统 OpenSSL。密码、证书和私钥保存在 KiraAI 的 `plugin_data/phone_control/identity.json`，通过同目录临时文件原子替换；POSIX 下按私密文件权限创建。更新插件时不能清除该数据目录。证书到期或 IP 更换后，重新保存会生成新证书，需要重新复制校验码。

App 校验指纹、有效期及主机名/IP。已有可信 CA 证书时可继续使用旧代理路由；关闭 `builtin_server` 即可保留手动接入。自定义 `device_token` 优先于自动密码。管理页与 setup、APK API 继承 KiraAI 登录校验；敏感 JSON 禁止缓存，保存请求需要自定义请求头。凭据不通过 LLM 工具暴露。独立手机端口不提供管理页、密码或文件下载。

KiraAI 插件保存进程内连接状态，内置服务运行时使用单 worker。独立端口默认 8443；公网安全组、系统防火墙和 Docker 端口映射需要由部署者配置。IPv4 绑定 0.0.0.0，IPv6 绑定 ::。最多同时处理 8 个手机握手/连接，握手限时 8 秒，WebSocket 消息上限 12 MB。停止插件时关闭连接并释放端口。

触摸参数以 0–1000 归一化，App 在主线程派发前核对屏幕尺寸和命令有效期。取消后已经交给 Android 执行的手势不保证可撤回。

## 构建

本地构建使用 Windows、JDK 21、Android SDK 36、Build Tools 36.0.0、Gradle 9.2.1、AGP 9.0.1，以及 HBuilderX / Vapor Android SDK 5.26。手机最低 Android 8，不等于编译 SDK 版本。

下面的准备脚本从官方地址下载固定版本并验证 SHA-256，写入 `.runtime/uni-tools`。资源编译使用 HBuilderX 自带的 Node，不会提交云打包、上传代码或申请 AppID。`__UNI__KIRAPHONE` 是本地资源与 APK 约定的标识；改用云打包时须自行配置 DCloud 要求的账号与 AppID。

```sh
python scripts/prepare_uni_tools.py
python scripts/sync_release.py
python scripts/compile_uni.py --hbuilderx .runtime/uni-tools/HBuilderX
gradle --project-dir uni-app/native-android -PuniSdkDir=<Vapor-SDK绝对路径> assembleDebug
python scripts/verify_uni_apk.py uni-app/native-android/app/build/outputs/apk/debug/app-debug.apk
python scripts/package_release.py --apk uni-app/native-android/app/build/outputs/apk/debug/app-debug.apk
```

SDK 位于 `.runtime/uni-tools/sdk/Android-uni-app-x-vapor-SDK@101163-5.26`，把命令中的占位值换成绝对路径，Windows 建议正斜杠。`JAVA_HOME`、`ANDROID_HOME` 指向本机 JDK 和 SDK。Windows Java 若报临时 socket 路径错误，可将 `jdk.net.unixdomain.tmpdir` 和 `java.io.tmpdir` 指向真实存在的项目内临时目录。

长期更新使用固定私钥：构建 `assembleRelease` 后用 Android `zipalign`、`apksigner` 签名，再验证和打包。覆盖安装要求应用 ID 和签名一致，不能用 CI 临时生成的调试签名覆盖正式包。

离线工程必须显式包含页面用到的官方 UTS 扩展。例如 `uni.showModal` 由 `_uni-modal` 提供，需在 `uni-app/native-android/app/build.gradle` 的 `fileTree` 中保留 `uni-modal-release.aar`；`uni-prompt-release.aar` 不能替代它。只勾选 HBuilderX 的 UTS 插件或制作自定义基座不能修复这个独立发行 APK 的依赖遗漏。`scripts/verify_uni_apk.py` 会同时检查弹窗实现、方法注册及自动注册类。

1.0.0 使用的完整发布流程（本工作区已执行，签名口令由维护者保管；1.3.x 的发布包与记录已归档到 `.runtime/archive-dist/` 和 `.runtime/archive/`）：

```sh
# 1. 编译页面资源（本工作区 HBuilderX 在 .runtime/hbuilderx/HBuilderX）
python scripts/compile_uni.py --hbuilderx .runtime/hbuilderx/HBuilderX --platform android
# 2. 打未签名 release APK
gradle --project-dir uni-app/native-android -PuniSdkDir=<Vapor-SDK绝对路径> assembleRelease
# 3. 对齐、签名、验证（$BT = $ANDROID_HOME/build-tools/36.0.0，需先设 JAVA_HOME）
$BT/zipalign -P 16 -f 4 uni-app/native-android/app/build/outputs/apk/release/app-release-unsigned.apk aligned.apk
$BT/apksigner sign --ks .runtime/phone-debug.keystore --ks-key-alias androiddebugkey --out KiraAI-Phone-Assistant.apk aligned.apk
$BT/apksigner verify --print-certs KiraAI-Phone-Assistant.apk
# 4. 校验并打包 dist/<版本号>
python scripts/verify_uni_apk.py KiraAI-Phone-Assistant.apk
python scripts/package_release.py --apk KiraAI-Phone-Assistant.apk
```

签名后 APK 证书 SHA-256 应与过去发布保持一致（`7fd2b427…9943d`），否则覆盖安装会失败。当前版本与递增的 versionCode 以 `release.json` 为准；本版特意重置为 1.0.0/code 1，已安装 1.1.9/code 11 的手机不能覆盖降级，必须先保存连接信息再卸载旧 App。`package_release.py` 会在打包前校验版本元数据，不一致时提示先运行 `python scripts/sync_release.py --write`。

发布输出在 `dist/<版本号>/`，包含独立 APK、不含 APK 的插件 ZIP、源码 ZIP、新手说明与 SHA-256 清单。源码包括 uni-app、UTS 和离线工程，排除编译输出、工具缓存与密钥。只打插件运行 `python scripts/package_plugin.py`。`package_release.py --apk` 仅复制独立手机安装包，不再嵌入插件。插件 ZIP 及解压总量均不得超过 50 MiB。

版本以 `release.json` 为准，修改后运行 `python scripts/sync_release.py --write`，同步插件、Android、uni-app 和协议常量。服务只编辑 `android-app/app/src/main/java/top/kira/phone/`，再运行 `python scripts/sync_uni_native.py --write` 同步桥接模块；不带 `--write` 只校验。每次原生变化后重新编译资源与 APK。

网页预览：`python scripts/compile_uni.py --hbuilderx <HBuilderX目录> --platform web`，输出在 `uni-app/unpackage/dist/build/web`。网页只演示界面偏好，不连接手机，连接配置的保存与启动会明确提示需使用 APK。圆心扩散由 Android 原生动画提供，网页不能证明真机效果。

## 看图与工具结果链路

App 主动 WSS → `AppBridge` 请求关联 → `PhoneControlPlugin` 工具结果 → KiraAI `FuncToolManager` → `AgentExecutor` → 下一轮 Provider 请求。JSON 保留在 tool 消息，图片引用由执行器移到紧随其后的 user 消息；Provider 将会话媒体引用解析成带正确 MIME 的图片数据。历史保留引用而非大段 base64。

`phone_watch` 是 2–4 帧批量观察，间隔 0.5–2 秒。它不产生连续流或声音，不把控件文字冒充视频。动作只接受同会话、同连接且最新的有效截图，连续帧定位使用最后一张。`phone_report` 不占设备锁，其他操作期间仍可发送进度。

新 App 接收截图参数 `image_format=jpeg|png`，默认请求 JPEG 85；旧 App 忽略此字段继续返回 PNG。旧插件请求没有该字段时，新 App 默认 PNG，协议仍为 1。服务器校验已缩小图片后保留原字节，超尺寸才缩放编码；`Screen.png` 是兼容字段名，实际类型由 `Screen.mime` 表示。`timing_ms` 记录截图往返与存储/投递时间，不包含随后模型推理耗时。新安装的 `action_delay` 为 0.25 秒。

## 测试命令

安装 KiraAI 源码及其依赖、`phone_control/requirements.txt`、pytest 和 pytest-asyncio，并将 `KIRAAI_ROOT` 环境变量设为 KiraAI 源码目录。

```sh
python -m pytest phone_control/tests deploy/test_setup_public_ip.py scripts/test_release.py -q
python scripts/test_android_gate.py
python android-app/tests/run_runtime_regressions.py
# Android 构建解析依赖后，运行真实 TLS/握手关闭检查：
python android-app/tests/run_socket_regressions.py --java-home <JDK目录> --gradle-home <Gradle缓存目录>
node --test scripts/test_ui_interactions.mjs scripts/test_ui_regressions.mjs
```

Java 检查覆盖指令门控和地址转换，可用 `--java-home` 指定 JDK。界面测试覆盖总开关全部组合和真实连接状态。APK 验证脚本解析 DEX 类定义，确认桥接方法与服务确实被编译。CI 使用 Windows 构建 uni-app，插件测试在 Linux 执行；实际结果见 [VALIDATION.md](VALIDATION.md)。

## 通话开发

控制和语音使用不同 WSS 连接，语音路径为 `/ws/plugin/phone_control/voice`。UTS 只传状态与控制调用，PCM 和播放数据留在 Java。新原生类必须加入 `scripts/sync_uni_native.py` 再同步，禁止直接改模块副本。协议、取消与真机验收见 [VOICE-PLAN.md](VOICE-PLAN.md)。
