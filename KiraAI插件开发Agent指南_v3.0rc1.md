# KiraAI 插件开发 Agent 指南

> **请求创作人：@znq19**
> 最后修订时间：2026-10-12（对齐 KiraAI **`v3.0.0-rc.1`**，提交 `8a0b812`）
> 定位：给 AI Agent 的**单文件前置上下文**——用户只需投喂本 MD，即可开始开发/修改 KiraAI 插件
> **铁律（最高优先级）**：本文未写明的框架内部细节 **禁止臆造、禁止猜 API**。缺什么就向用户要什么（路径/源码/文档），要不到就停手说明，不要编造方法名、字段或 adapter action。

---

## Agent 启动指令（读到本文档即生效）

**你正在阅读 KiraAI 机器人框架的 AI 用开发指南。**
请先**完整阅读并理解**本文档全部内容，将其作为后续工作的**前置重要参考资料**。

用户后续会请你：开发/设计插件、修改功能、排查问题。在此之前与过程中，请遵守：

1. **先读完再动手**：未读完全文前，不要开始写代码或下结论。
2. **以本文为准**：目录结构、装饰器、事件流、API、陷阱与适配器筛选等，均按本文实现；不要用其他框架的习惯硬套。
3. **缺文件就问（再次强调，不可违反）**
   - 本文是**充分但不完备**的开发上下文：能覆盖标准插件开发，**不等于**覆盖全部 `core/` 实现。
   - 凡本文未明确写出的内容——例如具体 adapter 的 `send_action` 名与参数、`self.ctx.db` 未列出的方法、Provider 内部实现、WebUI 鉴权细节、项目私有封装等——**一律禁止臆造**。
   - 需要时**主动向用户说明要哪些文件/路径**（如 `core/db/service.py`、某 adapter 源码、现有插件示例），等用户提供后再写相关代码。
   - 宁可少写、停下来问，也不要编造「看起来合理」的 API；臆造会导致插件加载失败或运行时报错。
4. **读完后简短确认**：用几句话概括你已掌握的核心能力边界（例如：能写标准插件、知道钩子/工具/配置/平台筛选、**不确定会索要源码**），然后等待用户的具体任务。
5. **开发时**：优先最小可运行结构；`initialize`/`terminate` 可重入；平台专有能力做能力查询（§1.2）；计数/状态勿误清。
6. **新代码注释一律英文**（仓库 AGENTS.md 规则）；插件能力优先暴露为 `@register.tool` / `@register.tag`（LLM 原生扩展点），勿用命令语法。

用户**无需**再单独发送「请先阅读开发指南」类说明——**打开/引用本文件即视为已下达上述指令。**

> **版本说明**：本文以 `v3.0.0-rc.1` 为当前事实基准。3.0 相对 2.x 有一批破坏性变更（会话接口全异步化、模型身份分离、适配器能力架构、插件模块拆分等），正文全部按 3.0 现状书写；如果你的插件必须同时兼容 2.x 老版本，看**附录 A「2.x 差异速查」**，那里给出特征识别（不绑版本号）的双世代写法。

---

## 0. 最小可运行插件

### 0.1 目录

```text
data/plugins/<plugin_id>/
  ├── main.py              # 入口（也可 plugin.py / __init__.py）
  ├── manifest.json        # 必须
  ├── schema.json          # 可选：WebUI 配置
  ├── requirements.txt     # 可选：安装时 pip install
  ├── provider/            # 可选：插件自带 Provider 组件目录
  └── adapter/             # 可选：插件自带 Adapter 组件目录
```

入口查找顺序：`main.py` → `plugin.py` → `__init__.py`
用户插件：`data/plugins/`；内置：`core/plugin/builtin_plugins/`
配置保存：`data/config/plugins/<plugin_id>.json`
插件数据：`data/plugin_data/<plugin_id>/`（`ctx.get_plugin_data_dir()`）

### 0.2 manifest.json（完整字段，v3.0.0-rc.1）

```json
{
  "plugin_id": "my_plugin",
  "display_name": "My Plugin",
  "version": "1.0.0",
  "author": "you",
  "description": "插件描述",
  "repo": "https://github.com/...",
  "tags": ["tools"],
  "core_version": ">=2.34.8",
  "locales": {
    "zh": { "display_name": "我的插件", "description": "中文描述" }
  },
  "icon": "icon.png",
  "icon-dark": "icon_dark.png",
  "hide": false,
  "uninstallable": false
}
```

- `plugin_id` 必须与目录名一致
- `core_version` 可选，PEP 440 版本约束；框架以 `SpecifierSet(prereleases=True)` 校验——`">=2.34.8"` 这类**只有下界**的声明对 3.0 的 alpha/rc/正式版全部放行。**不要写上界**（如 `<3.0`），否则未来大版本会被误挡
- `repo`：插件仓库 URL（WebUI 显示/更新用）
- `locales`：多语言显示名/描述
- `icon` / `icon-dark`：相对插件目录的图标路径
- `hide` / `uninstallable`：仅内置插件有效（隐藏列表 / 允许卸载内置插件）
- 插件状态机：`pending → installing → loading → ready | disabled | error`
- **安装包限制**：zip ≤ 50 MiB、条目 ≤ 10000、压缩比 ≤ 100:1、中央目录 ≤ 512 KiB
- **热重载**：框架先调 `prepare_plugin_reload(id)`（terminate → 清 class/schema/error → 清 sys.modules）再重新 import，插件无需自处理
- **当前核心版本**见 `core/config/default.py` 的 `VERSION`（本次对齐为 `v3.0.0-rc.1`）

### 0.3 main.py 最小模板

```python
import asyncio
from core.plugin import BasePlugin, logger, on, Priority, register
from core.chat.message_utils import KiraMessageBatchEvent, KiraMessageEvent
from core.provider import LLMRequest, LLMResponse
from core.chat.message_elements import Text
from core.chat import MessageChain

class MyPlugin(BasePlugin):
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        # section 字段以嵌套 dict 出现
        basic = cfg.get("section_basic", {})
        self.enabled = basic.get("enabled", True)
        self._task: asyncio.Task | None = None

    async def initialize(self):
        """成功后才会注册工具/钩子/标签/API/页面。"""
        logger.info("[my_plugin] initialized")

    async def terminate(self):
        """必须可重入：热重载会再次调用。取消 task、关连接、清状态。"""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    @register.tool(
        name="my_tool",
        description="当用户需要查询 X 时调用。",
        params={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询内容"}
            },
            "required": ["query"],
        },
    )
    async def my_tool(self, event: KiraMessageBatchEvent, query: str) -> str:
        return f"结果：{query}"

    @on.llm_request()
    async def inject_prompt(self, event: KiraMessageBatchEvent, req: LLMRequest, tag_set, *_):
        for p in req.system_prompt:
            if p.name == "tools":
                p.content += "\n额外工具说明"
                break
```

> 模块导入**只走包级**（`from core.plugin import ...` / `from core.chat import ...`）。3.0 起插件内部模块已拆分（`core/plugin/{base,handlers,manager,metadata,decorators,pages,components}.py`），旧的 `core.plugin.plugin_registry` / `core.plugin.plugin_handlers` 已删除——包级导入两代都安全，子模块深路径不要写死。

---

## 1. 核心概念速查

| 概念 | 说明 |
|------|------|
| 基类 | `BasePlugin`（`core.plugin.base`；包级导出），必须实现 `initialize()` / `terminate()` |
| 配置 | `schema.json` → WebUI；运行时 `cfg` 与 `self.plugin_cfg` 同一份 dict |
| 会话 ID `sid` | `adapter_name:dm\|gm:session_id`，如 `qq:dm:123`、`qq:gm:456`；内置 WebUI 聊天为 `webchat:dm:admin` |
| 私聊判断 | `not event.is_group_message()` 或 `sid.split(":")[1] == "dm"` |
| 群聊判断 | `event.is_group_message()` → 看 `message.group is not None` |
| 是否被提及 | `event.is_mentioned`（只读属性 → `message.is_mentioned`）；写入用 `event.message.is_mentioned = True` |
| 启用状态 | `data/config/plugins.json`；默认启用；禁用只 `terminate`，不删代码 |
| 热重载 | `terminate` → 清模块 → 重 import → 再 `init_plugin` |
| 平台相关能力 | **框架不会**按平台过滤插件；依赖平台能力的逻辑须在插件内自查（见 §1.2，3.0 用能力查询） |

### 1.0 插件加载与绑定顺序（官方，极重要）

```text
1. 扫描目录，import 模块
2. 装饰器 @register.* / @on.* 在 import 时登记到 PluginComponents（尚未绑定实例）
3. 读取 schema.json → 与已有配置合并默认值 → 写入 data/config/plugins/<id>.json
4. instance = PluginClass(ctx, cfg)
5. await instance.initialize()     ← 成功才继续；失败则丢弃实例
6. 绑定并注册：
   - tools  → `getattr(instance, func.__name__)` 绑定 self 后 `ctx.tool_mgr.register_tool`
   - hooks  → 绑定 self 后 event_handler_reg.register
   - tags   → 绑定 self 后 tag_registry.register
   - api/ws/page/static/widget → 挂到 FastAPI（若 web_app 已就绪）
```

含义：
- **`initialize()` 失败 = 工具/钩子都不会生效**
- 装饰器写在类方法上即可，框架会在 init 成功后绑定到实例（`self` 可用）
- 配置热更新会重新 `terminate` + 新实例 + `initialize`，内存状态会丢，需文件/DB 持久化

### 1.1 消息处理主流程（3.0 阶段管线）

3.0 把 IM 处理拆成独立阶段（`core/workflow/src/im/stages/`），服务经 `IMWorkflowContext` 注入：

```text
IM 消息到达
  → ReceiveStage → ON_IM_MESSAGE (@on.im_message)  可改策略
  → RouteStage: trigger | buffer | flush | discard
  → ON_MESSAGE_BUFFERED (@on.message_buffered)  参数是 sid:str
  → debounce / flush
  → PrepareBatchStage → ON_IM_BATCH_MESSAGE (@on.im_batch_message)
  → BuildRequestStage：消息链转文本（VLM/STT/文件落地）+ 结构化历史存档
  → [Skills prompt 注入（框架自动，tools 段之后）]
  → AssembleRequestStage：构建 LLMRequest + TagSet
  → ON_LLM_REQUEST (@on.llm_request)  注入 prompt/工具/标签
  → ExecuteAgentStage（每步）:
        调 LLM
        → ON_LLM_RESPONSE  （含 tool_calls 中间步！）
        → 若有 tool_calls → 执行工具 → ON_TOOL_RESULT → 继续
        → 否则 parse_xml → AFTER_XML_PARSE → 逐链发送
        → ON_MESSAGE_SENT / ON_STEP_RESULT
  → FinalizeStage：ON_FINAL_RESULT (@on.final_result)  整轮一次
  → 保存会话记忆（SQLite 持久化，见 §3.2）
```

**关键**：`ON_LLM_RESPONSE` 在 Agent **每一步**都会触发，包括仅有 `tool_calls` 的中间步。若只想在"最终文本回复"做事，必须：

```python
@on.llm_response()
async def on_resp(self, event, resp: LLMResponse, *_):
    if resp.tool_calls:
        return  # 跳过工具中间步
    text = (resp.text_response or "").strip()
    ...
```

### 1.2 适配器 / 平台筛选与能力查询（插件侧约定，必读）

**事实**：插件加载后对**所有**适配器的消息都会进钩子。`manifest.json` **没有**官方字段能声明「仅 QQ 加载」。

3.0 起适配器统一为**能力架构**（`core/adapter/`）：适配器是 `BaseAdapter` 容器，能力对象（`IMCapability`/`FeedCapability`）登记其上。**判断能不能聊天/发图，不要按适配器类型判断，查能力**：

```python
from core.adapter import IMCapability

adapter = self.ctx.adapter_mgr.get_adapter(adapter_name)
if adapter is None:
    return  # 适配器不在
im = adapter.get_capability(IMCapability)   # 没有或同种多个会抛 ValueError——用 try 或先查 capabilities
```

- `adapter.get_capability(IMCapability)`：返回唯一匹配的能力实例；没有该能力（如 Bilibili 只开动态不开私信）或重复登记时抛 `ValueError`。
- `adapter.capabilities`：只读映射视图，可先 `IMCapability in adapter.capabilities` 判断（`capabilities` 以类型为键）。
- 需要经过统一发送历史/发送状态记录时，优先 `await self.ctx.send_message_chain(sid, chain)`；确需平台直发（如指定群号主动推送）才调 `im.send_group_message(...)` / `im.send_direct_message(...)`。
- **QQ 适配器保留了旧式委托方法**（`adapter.send_group_message` 等内部转到 IM 能力）——2.x 写法在 3.0 上仍能跑，但新代码请走能力对象（其它适配器不一定有委托）。
- **表情目录**：旧 `adapter.emoji_dict` 已废弃；用 `meta = await im.get_message_metadata()`，读 `meta.supported_elements`（可输出格式，如 `["text","img","emoji"]`）与 `meta.emojis`（`None`=不支持表情）。
- **输出标签名与存档元素类型不同**：图片输出标签是 `img`，结构化历史链里的图片类型是 `image`，别混用。

#### 何时必须筛选

| 场景 | 示例 |
|------|------|
| 调用平台专有 API | OneBot `send_forward_msg`、戳一戳、群禁言、拉历史 |
| 消息段/能力不通用 | QQ 合并转发节点、特定表情 ID |
| 业务只服务某平台 | 仅 QQ 群管理、仅某 adapter 实例 |

通用能力（纯文本工具、LLM prompt 注入、跨平台 `send_message_chain`）**不必**强绑平台。

#### 判断字段（优先用这些）

```python
event.adapter.name       # 用户配置的适配器实例名，如 "qq"、"my_napcat"
event.adapter.platform   # 平台标识，如 "QQ"、"Telegram"（以实际 adapter 为准）
event.session.sid        # "qq:gm:123" → 前缀即 adapter_name
# 主动推送/无 event 时：
sid.split(":", 2)[0]     # adapter_name
self.ctx.adapter_mgr.get_adapter(name)
```

`name` 与 `platform` 不同：同一平台可有多个实例（`qq1`/`qq2`），`platform` 更适合「整类平台」判断。

#### 推荐写法（Agent 请直接套用）

```python
# 1) 钩子入口早退（最常用）
@on.im_message(priority=Priority.HIGH)
async def handle(self, event: KiraMessageEvent, *_):
    if event.adapter.platform != "QQ":  # 或 name not in self.allowed
        return
    ...

# 2) 工具内校验，给 LLM 明确失败原因
@register.tool(name="qq_poke", description="仅 QQ 可用：戳一戳", params={...})
async def qq_poke(self, event: KiraMessageBatchEvent, user_id: str) -> str:
    if event.adapter.platform != "QQ":
        return "当前会话不是 QQ，无法戳一戳"
    adapter = self.ctx.adapter_mgr.get_adapter(event.adapter.name)
    client = adapter.get_client()   # QQ(OneBot) 适配器保留 get_client()
    await client.send_action("send_poke", {...})
    return "已戳"

# 3) 配置白名单（多实例 / 用户可选）
# schema: allowed_adapters type=list，如 ["qq", "napcat"]
if self.allowed_adapters and event.adapter.name not in self.allowed_adapters:
    return
```

#### 内置 webchat 适配器（3.0）

框架内置管理员网页聊天适配器：名 `webchat`，路由 sid 固定 `webchat:dm:admin`。它由应用注册，**不是**可替换的用户适配器；你的插件钩子会照常收到它的消息（它走完整的消息链路）。做「全平台通用」功能时它自动覆盖；做 QQ 专有功能时按 `adapter.platform != "QQ"` 早退即可天然排除它。

#### 给 Agent 的决策规则

1. 功能是否依赖 **OneBot/QQ 专有 action、专有消息段**？→ **是则必须筛选**，并在 `description`/README 写明「仅 QQ/OneBot」。
2. 是否只用 `MessageChain` + `send_message_chain` / 通用 LLM？→ 默认**全平台**，不要硬编码 `platform == "QQ"`。
3. 不确定某 action 是否跨平台？→ **先筛选再调用**，或向用户索要目标 adapter 源码；禁止假设所有 adapter 都有 `send_action("...")`。
4. **发动态/评论用 `FeedCapability`**（见 §8）；IM 聊天用 `IMCapability`；两者都查不到 = 该平台不支持，静默 return（钩子）或返回可读错误字符串（工具）。
5. 筛选失败时：**静默 return**（钩子）或 **返回可读错误字符串**（工具），不要抛未捕获异常拖垮流程。

---

## 2. 装饰器

```python
from core.plugin import BasePlugin, on, Priority, register, logger
# 页面组件（包级导出）：
from core.plugin import PluginPage, PageMenu
```

> 3.0 起 `core.plugin.plugin_registry`/`plugin_handlers` 已删除；`EventType`、`Priority`、`event_handler_reg` 在 `core/plugin/handlers.py`，装饰器在 `core/plugin/decorators.py`，页面在 `core/plugin/pages.py`——**都经 `core.plugin` 包级导出，写包级导入即可**。

### 2.1 事件钩子 `@on.<event>(priority=...)`

框架调用为 `await handler.exec_handler(*args)`，下列为**实际传入位置参数**（不含 self）：

| 装饰器 | 实际参数 | 说明 |
|--------|----------|------|
| `@on.im_message` | `(event: KiraMessageEvent)` | 可设 trigger/buffer/flush/discard |
| `@on.message_buffered` | `(sid: str)` | **只有 sid**，不是 event |
| `@on.im_batch_message` | `(event: KiraMessageBatchEvent)` | 合并后的批量消息 |
| `@on.llm_request` | `(event, req: LLMRequest, tag_set: TagSet)` | 发 LLM 前；可改 prompt/tool_set/tag |
| `@on.llm_response` | `(event, resp: LLMResponse)` | Agent **每步**；含 tool 中间步 |
| `@on.tool_result` | `(event, tool_result: ToolResult)` | 每个工具返回后；`event.stop()` 可中断后续工具 |
| `@on.after_xml_parse` | `(event, actions: list)` | `list[MessageChain \| RootTagAction]` |
| `@on.message_sent` | `(event, action: MessageChain, result: KiraIMSentResult)` | 每条 MessageChain 发送后 |
| `@on.step_result` | `(event, step_result: KiraStepResult)` | 含 `message_results`、`raw_output` |
| `@on.final_result` | `(event, final_result: KiraFinalResult)` | **整轮一次**；`stop()` 不能撤回已发消息 |
| `@on.comment` | `(event: KiraCommentEvent)` | 评论事件（Feed 适配器；见 §4.3） |
| `@on.loaded` | 无业务 event | 全部插件加载完一次 |
| `@on.shutdown` | 无业务 event | 系统关闭前 |
| `@on.exception` | `(event, exc_event: KiraExceptionEvent)` | 异常 |
| `@on.custom_event` | `(custom_event: KiraCustomEvent,)` | 可用 `event_name=` 过滤 |

写法建议：一律加 `*_` 吸收多余参数。
**优先级**：`SYS_LOW=-100 / LOW=-50 / MEDIUM=0 / HIGH=50 / SYS_HIGH=100`；`SYS_*` 留给系统（用户插件勿用）。数值越大越先执行。

#### 仅 `@on.im_message` 有效的处理策略

```python
event.trigger(force=False)  # 立即处理，跳过 debounce
event.buffer(force=False)   # 进缓冲区
event.flush(force=False)    # 加入缓冲并立即刷出
event.discard(force=False)  # 丢弃
event.stop()                # 中止后续钩子
```

`force=True` 后后续钩子无法覆盖策略。默认策略是 `discard`。

### 2.2 工具 `@register.tool`

```python
@register.tool(name="weather", description="查询城市天气", params={...})
async def weather(self, event: KiraMessageBatchEvent, city: str, days: int = 3) -> str:
    return f"{city} 晴"
```

- 框架执行：`await tool.execute(event, **args)`（见 `core/agent/func_tool_manager.py` 的 `FuncToolManager.execute_tool`）
- 第一个位置参数是 `event`；其余来自 LLM 的 JSON 参数（关键字）
- 参数名必须与 schema `properties` 一致
- 返回 `str` / 任意可 `str()` 的值 / `ToolResult`
- 有超时：`bot_config.agent.tool_call_timeout`（默认 60s）；每轮上限 `max_tool_calls_per_turn`（默认 5）
- 绑定：init 成功后用 `getattr(instance, method_name)` 绑定，**方法名不要随意改别名**

**工具给模型返图**——把图片作为 `media_refs` 交回主模型；框架会把 refs 挪到工具结果之后的一条 `role="user"` 消息（部分 provider 不接受 tool 角色带图）。**禁止**自己往 tool 消息里塞 `image_url`：

```python
from core.agent.tool import ToolResult
from core.chat.message_elements import Image
from core.utils.media_refs import store_session_media

@register.tool(name="read_chart", description="读取图片并让主模型直接看图", params={
    "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"],
})
async def read_chart(self, event: KiraMessageBatchEvent, path: str) -> ToolResult:
    media_ref = await store_session_media(
        Image(image=path),                 # mime 可省略（按内容推断）
        event.sid, event.messages[-1].message_id,
    )
    return ToolResult(text=f"Image file: {path}", media_refs=[media_ref])
```

- `media_refs` 在持久化历史里只存紧凑路径（`kira_image_ref`），按请求再解析成 image parts，历史不会膨胀。
- **`attachments=[Image(...)]` 是另一回事**：它把路径列进工具文本、提示模型用 `<file>` 标签把附件"发出去"，模型**看不到**图片内容。
- 工具从磁盘读图想按全局压缩设置压一下：`compress_image_file(path, self.ctx.config.get_config("bot_config.image_compression", {}))`。

动态注册（全局工具表 `FuncToolManager`，所有会话可见）：

```python
self.ctx.tool_mgr.register_tool(name, description, parameters, func)
self.ctx.tool_mgr.unregister_tool(name)
```

按需注入（仅当前请求，推荐复杂/条件工具）：

```python
from core.utils.tool_utils import BaseTool

class WeatherTool(BaseTool):
    name = "weather"
    description = "..."
    parameters = {"type": "object", "properties": {...}, "required": [...]}

    def __init__(self, ctx, plugin):
        self.ctx = ctx
        self.plugin = plugin

    async def execute(self, event, city: str, *args, **kwargs) -> str:
        return "..."

@on.llm_request()
async def inject(self, event, req: LLMRequest, *_):
    req.tool_set.add(WeatherTool(self.ctx, self))
```

**MCP 工具**：MCP 服务器工具由框架自动注册进全局 tool_set（`core/agent/mcp_mgr.py`），插件**无需**手动处理。scope 过滤（`is_server_allowed(server_id, sid)`）由框架在每请求构建 tool_set 时执行；单工具禁用：`mcp.json` 顶层 `_disabledTools` 或 `MCPManager.set_tool_enabled(server_id, tool_name, enabled)`。插件若需查询 MCP 状态，用 `self.ctx.mcp_mgr`（3.0 起 PluginContext 规范入口）。

### 2.3 标签 `@register.tag`

```python
@register.tag(name="thinking", description="思考过程", parent="msg")  # parent=None 为根标签
async def thinking_tag(self, value: str, **attrs):
    return Text(f"[思考：{value}]")  # 也可 list[元素] / str / None
```

- 消息内标签（`parent="msg"`）：解析后变成消息元素，进入 `MessageChain`
- 根标签（`parent=None`）：发送阶段执行 `RootTagAction`，可只做事不产出消息
- 也可在 `@on.llm_request` 里对本次请求的 `tag_set` 动态 `register`

### 2.4 API / 页面 / 静态 / WS / Widget

```python
@register.api(method="GET", path="/status", auth=True, summary="状态")
async def api_status(self):
    return {"ok": True}
# 最终路由：/api/plugin/{plugin_id}/status
# kwargs 透传 FastAPI add_api_route（response_model, summary, ...）

@register.page("/dashboard", auth=True, menu=PageMenu(label={"zh": "仪表盘"}, icon="Monitor", order=100))
def dashboard(self):
    return PluginPage.from_html("<h1>OK</h1>")
    # 或 PluginPage.from_folder("./web") / from_url("https://...")
# 最终：/page/plugin/{plugin_id}/dashboard
# PageMenu.icon：可传 SVG 文件路径（相对插件根，如 "assets/icon.svg"），也仍是 Element Plus 图标名
# 插件页面/静态资源由框架以 Cache-Control: no-store 提供：更新插件后无需清浏览器缓存

@register.static(path="/assets", directory="./assets", html=False)
def assets(self): pass
# html=True 时目录请求尝试 index.html
# 最终：/static/plugin/{plugin_id}/assets

@register.ws(path="/stream", auth=True)
async def ws_stream(self, ws): ...
# auth=True 时握手后 ws.state.user 可用
# 最终：/ws/plugin/{plugin_id}/stream

@register.widget(label={"zh": "计数"}, icon="ChatDotRound", color="blue", size="small", order=100)
async def widget_count(self) -> str:
    return "42"  # wide 可返回 HTML
```

---

## 3. PluginContext API（3.0 精确版）

### 3.0 字段与直达属性

```python
self.ctx.get_plugin_data_dir()          # Path：data/plugin_data/<plugin_id>/
# 注意：通过 inspect 调用栈解析 plugin_id，请在插件自身代码中调用，勿包一层无关模块再调
self.ctx.get_plugin_inst("other_id")    # 其他插件实例或 None

# 模型客户端（见 §3.4 模型身份）
self.ctx.get_default_llm_client()
self.ctx.get_default_fast_llm_client()
self.ctx.get_llm_client("provider_id:model_id")   # 冒号后 = 内部稳定 ID（3.0 起）
self.ctx.get_llm_client(llm_type="default"|"fast")
self.ctx.get_default_embedding_client()
self.ctx.get_embedding_client("provider_id:model_id")

# 会话与缓冲
self.ctx.get_buffer(sid)                # SessionBuffer（buffer/lock 字段两代一致）
await self.ctx.get_session_capabilities(sid)   # ⚠️ 3.0 起是异步！合并全局+会话覆盖
published = await self.ctx.flush_session_messages(sid, filter_fn=None)
#   filter_fn：同步谓词 (KiraMessageEvent)->bool；返回 True=已发布批次，False=无匹配
#   （不代表 Agent 已执行完；未匹配事件留在缓冲区）
await self.ctx.publish_notice(sid, MessageChain([...]), is_mentioned=True)
await self.ctx.send_message_chain(sid, MessageChain([...]))  # → KiraIMSentResult
await self.ctx.emit_custom_event("name", payload={})
self.ctx.get_lang()                     # 'zh'/'en'，默认 'en'
self.ctx.get_timezone()                 # ZoneInfo | None

# 插件自带 Provider / Adapter
await self.ctx.register_provider("provider")    # 相对插件目录；目录内需 manifest.json
await self.ctx.unregister_provider("format")
await self.ctx.register_adapter("adapter")
await self.ctx.unregister_adapter("platform")

# 直接属性（3.0 完整注入面）
self.ctx.db                  # DatabaseService
self.ctx.config              # KiraConfig
self.ctx.event_bus           # EventBus
self.ctx.provider_mgr        # ProviderManager
self.ctx.tool_mgr            # FuncToolManager
self.ctx.adapter_mgr         # AdapterManager
self.ctx.persona_mgr         # PersonaManager（3.0 含参考图/场景规则，见 §3.5）
self.ctx.sticker_mgr         # ⚠️ 3.0 规范名；旧名 sticker_manager 只有只读别名属性（构造关键字/赋值不支持）
self.ctx.session_mgr         # SessionManager（3.0 全异步，见 §3.2）
self.ctx.message_processor   # MessageProcessor（仅剩转发/兼容入口，见 §3.1）
self.ctx.prompt_mgr          # PromptManager
self.ctx.skills_mgr          # SkillsManager（勿再 message_processor.skills_manager）
self.ctx.mcp_mgr             # MCPManager | None（勿再 message_processor.mcp_manager）
self.ctx.message_history     # MessageHistoryService（结构化消息存档，见 §3.3）
self.ctx.image_desc_cache    # ImageDescCache
self.ctx.session_buffer_mgr  # SessionBufferManager
self.ctx.message_delivery    # MessageDeliveryService（统一发送+解析，见 §3.1）
self.ctx.plugin_mgr          # PluginManager | None
```

### 3.1 消息服务与 MessageProcessor（3.0 重构后）

`MessageProcessor` 只剩薄转发（构造 `MessageProcessor(im_workflow)`），插件应改用明确的服务：

| 需求 | 3.0 正确入口 |
|------|--------------|
| 发送消息 | `await ctx.send_message_chain(sid, chain)`（经发送历史/状态）或 `ctx.message_delivery.send_message_chain(...)` |
| 冲刷缓冲 | `await ctx.flush_session_messages(sid, filter_fn=...)` |
| XML 解析 / 消息 ID 回填 | `ctx.message_delivery.parse_xml(text, tag_set)` / `.add_message_ids(...)`（静态方法） |
| 消息链文本化 | `ctx.message_processor.im_workflow.ctx.message_formatter.format_to_text(chain, ...)`（异步）；逐层 `getattr` 探测 |
| 媒体取图/原生内容 | `MessageMediaService.iter_images(...)` / `build_native_content(...)`（`core/workflow/src/im/`） |
| 读缓冲 | `ctx.get_buffer(sid)`：`buf.buffer`（list）、`buf.lock`、`buf.get_length()`、`buf.pop(count)` |
| 注入合成消息 | `await ctx.event_bus.publish(event)`（单条） |
| 图片描述缓存 | `ctx.image_desc_cache`（运行实例生命周期系统管理） |

### 3.2 会话记忆 / 会话信息（⚠️ 3.0 最大破坏面：全异步 + SQLite 持久化）

`SessionManager` 不再有常驻 `chat_memory` 缓存，不再有旧的同步记忆 API。会话读取返回**独立快照**（改快照不会自动写回），写必须显式调接口：

```python
sm = self.ctx.session_mgr

sessions = await sm.get_sessions(include_content=False)  # 轻量列表（不含正文）
session = await sm.get_session(sid)                       # 不存在返回 None
session = await sm.get_session(sid, ensure_session=True)  # 显式创建缺失会话
chunks = session.content                                  # list[list[dict]] 分块上下文
flat = session.flatten_content()                          # list[dict] 拍平
await sm.update_session(sid, title=..., description=...)  # 省略字段保持原值
await sm.update_session(sid, content=chunks)              # content 整体替换（非增量合并）
await sm.update_session(sid, data={...})                  # data 整体替换（能力覆盖在 data['capabilities']）
await sm.update_memory(sid, new_chunk)                    # 追加一块（框架回复后也调）
count = len(session.content)                              # 或批量 await sm.get_session_message_counts()
await sm.get_effective_capabilities(sid, global_caps)     # 异步
await sm.update_session_capabilities(sid, capabilities)   # 异步；None 恢复跟随全局
await sm.delete_session(sid)                              # 异步
```

**`Session` 字段**：`adapter_name` / `session_type`("dm"|"gm") / `session_id` / `session_title` / `session_description` / `timestamp` / `content` / `data` / `internal_id`（`sess_<uuid>`，内部身份，不能替代路由 sid）/ `created_at` / `updated_at`；`sid` 属性 = `adapter:type:id`。

**规则要点**：
- `content` 结构 `list[list[dict]]`，角色只允许 `system/user/assistant/tool`；写入时框架规范化 `_extra.llm_message_id`。
- **清空上下文请用 `await sm.update_session(sid, content=[])`**（只清对话，标题/能力/data 保留）；**不要** `delete_session` + 重建（会把能力设置等元数据一起抹掉）。
- 旧 `data/memory/chat_memory.json` 在首次启动时一次性导入（保留原文件），之后不再读它。
- 会话事件 `session_memory_updated` / `session_memory_written` / `session_deleted` 在持久化完成后发布（事件总线，插件可 `ctx.event_bus.subscribe` 字符串名订阅）。
- 上下文长度仍受 `bot_config.bot.max_memory_length` 限制；溢出多丢几块由 `bot_config.bot.memory_overflow_discard_count` 控制。

### 3.3 结构化消息历史（3.0 新增）

平台实收发消息（含媒体）独立入库，与 LLM 上下文是两份数据——**不要把上下文条数当平台消息数**：

```python
page = await self.ctx.message_history.list_messages(sid, limit=50)   # {"messages": [...], "next_cursor": ...}
record = await self.ctx.message_history.get_message(message_id)
linked = await self.ctx.message_history.get_linked_memory(record)    # 对应的 LLM 上下文（无关联/已裁剪为 None）
page = await self.ctx.message_history.get_messages_by_llm_message_id(sid, llm_message_id, limit=50)
```

- 分页按存档创建时间+记录 ID 倒序；`limit` 1–200；游标必须属于该会话。
- `KiraIMSentResult` 新增 `history_id`（历史存档内部 ID）；`message_id` 仍是平台发送 ID，两者别混。
- 历史清理配置 `bot_config.message_history_cleanup`（默认启用、每会话最多 500 条、每 3600s 检查；`max_age_days=0` 不限天数），独立于上下文的 `max_memory_length`。

### 3.4 模型身份（3.0：内部 ID 与可读名分离）

```python
# ModelInfo 字段：model_type / model_id（内部稳定 ID，uuid 形态）/ provider_id / provider_name /
#                model_name（上游真实模型名）/ provider_config / model_config
# get_models(provider_id) 返回 {类型: {内部ID: {"model_name": ..., "config": {...}}}}
```

**插件铁律**：
- 发给上游 API 的 `model` 参数用 `model.model_name`（Provider 内部已处理，插件自定义 Provider 时注意）；
- 展示给用户的一律 `model_name` 优先（`getattr(info, "model_name", None) or info.model_id`），**绝不要把内部 ID 当名字显示**（用户看到的是 uuid 乱码）；
- 配置引用 `provider_id:model_id` 的冒号后是**内部 ID**；不要用展示名拼接引用；
- 旧配置迁移后带 `legacy_ids`（旧名可无歧义解析）；`schema` 的 `model_select` 字段由框架自动规范化，插件不用管；
- **文本型模型配置项**（用户手填名字的 string/list 字段）：框架不认任意显示名——插件要自己做「显示名 → 内部 ID」反查兜底（扫描 `get_model_infos(provider_id)` 按 `model_name` 匹配），否则用户按 2.x 习惯填名字会静默失效：

```python
def _resolve_display_ref(self, provider_id: str, model_name: str) -> str:
    """用户手填的「提供商:可读名」→ 框架可解析引用（特征识别，不绑版本号）。"""
    try:
        pm = self.ctx.provider_mgr
        for mi in pm.get_model_infos(provider_id) or []:
            if getattr(mi, "model_name", None) == model_name and getattr(mi, "model_id", None):
                return f"{provider_id}:{mi.model_id}"
    except Exception:
        pass
    return f"{provider_id}:{model_name}"  # 直通兜底（2.x / 迁移旧名 / 内部 ID 原样可用）
```

- Provider 可停用：`providers.<id>.status: active|inactive`；停用后 `get_model_client` 抛 `ProviderAPIError`（连已缓存客户端的新调用也会拦）——插件对模型调用失败要容错。
- 公共 OpenAI 兼容客户端在 `core.provider.openai_compatible`（`OpenAICompatibleLLMClient/TTS/STTClient`）；旧路径 `core.utils.model_clients` 已删除。

### 3.5 人设（3.0 增强）

```python
persona = await self.ctx.persona_mgr.get_active_persona()
# PersonaInfo 新增：reference_image_path / chat_rules / private_chat_rules / group_chat_rules
path = await self.ctx.persona_mgr.get_reference_image(persona_id)   # None 表示当前激活人设
path = await self.ctx.persona_mgr.set_reference_image(persona_id, image_bytes, filename)
await self.ctx.persona_mgr.remove_reference_image(persona_id)
```

- 规则组合 = 全局 + 当前私聊/群聊规则，由提示管理器注入。
- 旧全局 `bot_config.selfie.path` 会被一次性迁移到当前激活人设；**新代码不要读旧键**。

---

## 4. 事件与消息对象（官方字段）

### 4.1 KiraMessageEvent（单条）

```python
event.sid                    # 无此属性！用 event.session.sid
event.session.sid            # "qq:gm:123"
event.adapter                # AdapterInfo（.name / .platform）
event.supported_elements     # ⚠️ 3.0 起字段名（可输出元素清单）；旧名 message_types 是兼容别名
event.message                # KiraIMMessage
event.message.chain          # MessageChain
event.message.sender         # User(user_id, nickname)
event.message.group          # Group | None
event.message.message_id
event.message.self_id
event.message.is_mentioned   # 可写：event.message.is_mentioned = True
event.message.is_notice
event.message.raw_message / .extra
event.is_mentioned           # 只读属性 → message.is_mentioned
event.is_group_message()     # message.group is not None
event.trigger/buffer/flush/discard/stop()
```

**生产事件的字段名**：构造时优先 `supported_elements=`（3.0 规范）；旧关键字 `message_types=` 在 3.0 仍被兼容接受（不能与 `supported_elements` 混用），2.x 只认 `message_types`——跨世代代码按构造签名实测分流：

```python
import inspect
_params = set(inspect.signature(KiraMessageEvent.__init__).parameters)
kw = {"supported_elements": elems} if "supported_elements" in _params else {"message_types": elems}
event = KiraMessageEvent(adapter=adapter.info, message=msg, timestamp=ts, **kw)
```

**构造合成事件时的陷阱**（主动推送/定时任务必读）：

`KiraMessageEvent.__post_init__` 会**自动**根据 `adapter + group/sender` 生成 `session`。
若 sender 是 `system_xxx`，生成的 sid 会错，**必须事后覆盖**：

```python
from core.chat import KiraMessageEvent, KiraIMMessage, User, Group, Session, MessageChain
from core.chat.message_elements import Text

adapter = self.ctx.adapter_mgr.get_adapter(adapter_name)
group = Group(group_id=session_id) if session_type == "gm" else None  # 群聊必须带 group！

event = KiraMessageEvent(
    adapter=adapter.info,
    message=KiraIMMessage(
        timestamp=int(time.time()),
        sender=User(user_id="system_proactive", nickname="系统"),
        group=group,
        message_id="system_message",
        self_id=str(adapter.config.get("self_id", "") or ""),
        chain=MessageChain([Text("提示词")]),
        is_notice=False,
        is_mentioned=True,
    ),
    timestamp=int(time.time()),
    **_event_elements_kw(adapter),   # 见上面的双世代写法
)
# 覆盖为真实会话
event.session = Session(
    adapter_name=adapter_name,
    session_type=session_type,  # "dm" | "gm"
    session_id=session_id,
)
await self.ctx.event_bus.publish(event)   # 3.0：注入合成消息走事件总线
```

也可用官方封装（notice 场景）：

```python
await self.ctx.publish_notice(sid, MessageChain([Text("主动消息")]), is_mentioned=True)
```

### 4.2 KiraMessageBatchEvent（批量 / 工具参数）

```python
event.event_id
event.sid                    # = session.sid（有此属性）
event.adapter / event.session
event.messages               # list[KiraIMMessage]
event.is_group_message()
event.self_id
event.model_group            # 可指定模型列表
event.stop()
```

### 4.3 评论与 Feed（3.0 定型）

评论从旧社交适配器接口迁到 `FeedCapability`；事件是 `KiraCommentEvent`（`EventType.ON_COMMENT` + `@on.comment`）：

```python
# KiraCommentEvent 字段：comment_id / comment_content / target(FeedRef) / root_comment_id /
#   platform / adapter_name / commenter_id / commenter_nickname / self_id / timestamp
# 顶层评论的 root_comment_id = 自身 comment_id

from core.adapter import FeedCapability
from core.plugin import Priority, on

@on.comment(priority=Priority.HIGH)
async def reply_comment(self, event):
    event.stop()          # 接管：阻止后续插件与内置默认评论插件重复处理
    adapter = self.ctx.adapter_mgr.get_adapter(event.adapter_name)
    if adapter is None:
        return
    try:
        feed = adapter.get_capability(FeedCapability)
    except ValueError:
        return            # 该平台没有 Feed 能力
    await feed.send_comment(
        MessageChain([Text("收到")]),
        event.target,
        root=event.root_comment_id,
        parent=event.comment_id,
    )
```

- 在确定接管后、首次外部 `await` 前调 `event.stop()`；未接管的评论由内置默认评论插件以系统低优先级处理；用户插件勿用 `SYS_LOW/SYS_HIGH`。
- Feed 能力接口（全异步）：`get_feed(FeedQuery(...))->FeedPage` / `search_feed(FeedSearchQuery(...))` / `send_post(FeedPost(content=chain, extra=...))` / `send_comment(message, target, root=, parent=)` / `get_comment_metadata()` / `get_post_metadata()`；`FeedPage` 有 `items/next_cursor/has_more`，游标属于签发它的适配器实例。
- 直播/语音频道能力（`LiveEventCapability`/`VoiceChannelCapability`）**当前未提供**（预留接口已注释不导出），勿引用。

### 4.4 KiraCustomEvent（自定义事件）

```python
# 字段：event_name / source_plugin / payload(dict) / timestamp
# 发送：
await self.ctx.emit_custom_event("my_event", payload={"k": "v"})
# 接收（event_name 过滤）：
@on.custom_event(event_name="my_event")
async def on_my_event(self, custom_event, *_):
    data = custom_event.payload
# 不传 event_name = 接收所有自定义事件
```

**注意**：`KiraCustomEvent` 是单处理器事件类型，框架内部已订阅并转发到 `@on.custom_event` 钩子，插件走钩子即可，**勿直接 `event_bus.subscribe`**。

### 4.5 KiraExceptionEvent

```python
# name / message / traceback / stage / source("plugin"|"provider"|"adapter")
# comp_id(plugin_id|provider_id|adapter_name) / e(原始异常) / extra
```

### 4.6 KiraFinalResult

整轮消息处理结束（含全部 agent 步骤）后，随 `@on.final_result` 触发的聚合结果：

```python
@dataclass
class KiraFinalResult:
    step_results: list[KiraStepResult]   # 按执行顺序；每项含 message_results / raw_output
# 用途：判断单步 vs 多步（工具）轮；汇总本轮发送的消息与原始输出做统计/审计
# 注意：此时消息早已发出，event.stop() 只能阻止后续 final handler，不能撤回消息
# 3.0：AgentStepResult 的 model_id 是内部模型身份；新增 model_name（上游名）与
#      assistant_message（当前步骤的 OpenAIMessage，供发送存档关联）
```

### 4.7 MessageChain / 元素

```python
from core.chat.message_elements import (
    Text, Image, At, Reply, Forward, Emoji, Sticker,
    Record, Notice, Poke, Json, File, Video
)
from core.chat import MessageChain  # 或 message_utils.MessageChain

chain = MessageChain([Text("hi"), At("123"), Image("/path.jpg")])
chain.append(Text("x"))
# 迭代：for elem in chain: ...
# 内部列表：chain.message_list
# 取纯文本：
text = "".join(e.text for e in chain if isinstance(e, Text))
```

| 元素 | 构造要点 |
|------|----------|
| `Text("...")` | 纯文本，`.text` |
| `Image(image, mime=, name=, caption=)` | 首参名是 **image**；url/path/base64/data_url；mime 省略时按内容推断 |
| `At(pid, nickname=)` | `pid="all"` @全体 |
| `Reply(message_id, message_content=, chain=)` | 回复；`chain` 可嵌套 |
| `File(file, name=, size=, mime=)` / `Video` / `Record` | 继承媒体基类 |
| `Forward(chains=, message_id=, merge=True)` | 合并转发 |
| `Sticker(sticker_id=, sticker=, caption=)` | 贴纸 |
| `Emoji(emoji_id, emoji_desc=)` / `Poke(pid)` / `Json(data)` / `Notice(text)` | 其它 |

媒体通用（`Image/File/Video/Record/Sticker`）：

```python
path = await elem.to_path()      # 下载/解码到 data/temp/，返回本地路径
b64 = await elem.to_base64()
data_url = await elem.to_data_url()
elem.del_cache()                 # 删临时文件
```

发送：

```python
result = await self.ctx.send_message_chain(   # 3.0 统一入口（经发送历史）
    event.sid,  # Batch 有 .sid；单条用 event.session.sid
    MessageChain([Image("/path/a.jpg", caption="")]),
)
# result.ok / result.message_id / result.err / result.is_notice / result.history_id
```

TTS/STT/生图/VLM（`core/utils/common_utils.py` 辅助函数 + `ctx.provider_mgr.get_default_*()` 取客户端）：

```python
from core.utils.common_utils import text_to_speech, speech_to_text, generate_image, image_to_image, desc_img, image_to_base64

tts_client = self.ctx.provider_mgr.get_default_tts()      # TTSModelClient | None
record = await text_to_speech(tts_client, "你好")         # Record（语音）

stt_client = self.ctx.provider_mgr.get_default_stt()      # STTModelClient | None
text = await speech_to_text(stt_client, record)           # str（识别）

img_client = self.ctx.provider_mgr.get_default_image()    # ImageModelClient | None
img = await generate_image(img_client, "一只猫")          # Image（文生图）
img2 = await image_to_image(img_client, "改风格", image=Image(...))  # 图生图

# VLM 图片描述：client 是 LLMModelClient，取 default_vlm
vlm_client = self.ctx.provider_mgr.get_default_vlm()      # LLMModelClient | None
desc = await desc_img(vlm_client, img_elem, prompt=None, lang=None)  # str；img_elem 是 Image|Sticker
b64 = await image_to_base64(image_path)                   # 本地路径或 http(s) URL → base64 str

# 视频：客户端直接调方法
video_client = self.ctx.provider_mgr.get_default_video()  # VideoModelClient | None
vid = await video_client.generate_video(prompt="...", duration=5)  # Video
```

客户端可能为 `None`（未配置默认模型）；Provider 停用时会抛 `ProviderAPIError`——调用前判空、调用时容错；多模态能力可用能力开关查询（注意 3.0 异步）：`caps = await self.ctx.get_session_capabilities(sid)`（键：`image_recognition`/`tts`/`stt`/`image_generation`/`video_generation`/`forward_parsing`）。

---

## 5. LLMRequest / LLMResponse / ToolSet

### 5.1 LLMRequest

```python
req.messages          # list[OpenAIMessage]（pydantic，非裸 dict）
req.user_prompt       # list[Prompt]
req.system_prompt     # list[Prompt]
req.tool_set          # ToolSet（官方主路径）
req.tools             # 由 tool_set.to_list() 派生
req.tool_choice       # "auto" | "none" | "required"
req.assemble_prompt(dynamic_position="latest_user", memory_position="system")  # 框架在 ON_LLM_REQUEST 后调用
```

#### 动态段重定位（前缀缓存优化）

`DYNAMIC_PROMPT_NAMES = ("sessions", "chat_env", "time")` 三段内容每轮都变。配置 `bot_config.bot.dynamic_prompt_position` 默认 `"latest_user"`：assemble 时框架把这三段**原对象**标 `persist=False`、外包 `<system_reminder>...</system_reminder>` 挪到 **user_prompt 最前**，system prompt 因此跨轮稳定、前缀缓存可覆盖整段记忆；`"system"` 为旧行为。`memory` 段（`MEMORY_PROMPT_NAME="memory"`）由 `bot_config.bot.memory_prompt_position` 独立控制，默认同样 `"latest_user"`——读取 `user_prompt` 时它也在 `persist=False` 之列。

对插件的含义：

- 注入到 `sessions` / `chat_env` / `time` / `memory` 段的内容会随之进入最新 user 消息，且**不落记忆**（每轮现算）；注入其他 system 段仍留在稳定前缀里。
- **读取 `req.user_prompt` 时必须过滤 `persist=False`**（动态段、reminder 标记和 memory 段都在里面）：`[p for p in req.user_prompt if getattr(p, "persist", True)]`。
- 想加「每轮变化、用完即弃」的信息：追加到 `chat_env` 内容，或 `req.user_prompt.insert(0, Prompt(..., persist=False))`。
- **挪/复制 Prompt 必须动原对象**：模板靠 kwargs 在 `to_string()` 时才格式化（如 time 的 `{time_str}`），新建 Prompt 会丢 kwargs，模型看到未替换的字面量。

官方 `get_agent_prompt` 注入的 `system_prompt.name`（按顺序）：

| name | 含义 |
|------|------|
| `role` | 角色总述 |
| `persona` | 人格 |
| `attention` | 注意事项 |
| `output` | 输出/工具轮次要求 |
| `format` | XML 输出格式 |
| `accounts` | 账号列表 |
| `sessions` | 会话相关 |
| `chat_env` | 当前平台/群名/self_id 等 |
| `memory` | 记忆说明 |
| `tools` | 工具说明 |
| `time` | 当前时间 |
| `skills` | 技能（有启用技能时插入 tools 后） |

插件注入时优先 **追加到已有同名 Prompt**，没有再 `append` 新段。

```python
from core.prompt_manager import Prompt

@on.llm_request()
async def inject(self, event, req: LLMRequest, tag_set, *_):
    for p in req.system_prompt:
        if p.name == "chat_env":
            p.content += "\n额外说明"
            break
    else:
        req.system_prompt.append(Prompt("额外说明", name="chat_env", source="my_plugin"))
```

`Prompt(content, name=, source=, end="\n", persist=True, render_template=False, **kwargs)`
`persist=False` 的 user_prompt 不会写入记忆/日志（重定位的动态段即以此标记）；`render_template=True` 时用 jinja2 渲染 kwargs。

### 5.2 LLMResponse

```python
resp.text_response      # str
resp.reasoning_content  # str
resp.tool_calls         # list[dict]  OpenAI 格式；中间步非空
resp.tool_results       # list[dict]
resp.agent_step_index
resp.input_tokens / output_tokens / cached_tokens / time_consumed
```

### 5.3 ToolSet（极易写错）

```python
# 官方 core/agent/tool.py
# tool_set.tools 是 list[BaseTool]，不是 OpenAI function dict！

# ❌ 错误（会 AttributeError 或静默失败）
for tool in req.tool_set.tools:
    name = tool.get("function", {}).get("name")

# ✅ 正确
for tool in list(req.tool_set.tools):
    name = tool.name
req.tool_set.remove("tool_a", "tool_b")
req.tool_set.add(my_tool_instance)
req.tool_set.get("weather")
req.tool_set.to_list()  # → OpenAI tools JSON
```

`BaseTool`（`core/utils/tool_utils.py`）：

```python
class BaseTool(ABC):
    name = None
    description = None
    parameters = None
    async def execute(self, *args, **kwargs) -> str: ...
    def get_schema(self) -> dict: ...  # name/description/parameters
```

`ToolResult`（`core/agent/tool.py`）：

```python
ToolResult(
    text="...",
    attachments=[Image(...), File(...), Record(...)],  # 旧「附件」通道：列路径，提示模型用 <file> 发送
    media_refs=[{"type": "kira_image_ref", "path": ..., "mime_type": ..., "detail": ...}],  # 让模型直接看图
)
# media_refs 用 `await store_session_media(Image(image=path), sid, message_id)` 生成；
# 框架把 refs 挪到工具结果之后的一条 user 消息（部分 provider 不接受 tool 角色带图）。
# ToolResult.build_content(text) / assemble_result() 由框架调用，插件无需手动调。
```

---

## 6. schema.json 配置系统

### 6.1 字段类型（官方 `create_field_from_schema`）

| type | 说明 | 额外 |
|------|------|------|
| `string` / `text` | 单行；**支持 `options`**（渲染成下拉） | default 不在 options 里则强制为 `options[0]` |
| `integer` / `int` | 整数；同样支持 `options` | WebUI 可写 minimum/maximum（框架不校验） |
| `float` | 浮点；同样支持 `options` | **没有 `number` 类型**；写 `number` 会回落成 string |
| `sensitive` | 密码框 | |
| `switch` / `bool` / `boolean` | 布尔 | default 非 bool 强制 `false` |
| `list` | 多行列表 | default `[]` |
| `enum` | 下拉 | **已废弃**，仅为旧插件兼容；改用 `string`/`integer`/`float` + `options` |
| `multi_select` | 多选 | 静态 `options`，或 `source: "model"/"persona"/"session"`（+`model_type`）/ `allow_custom: true`；default `[]` |
| `session_select` | 会话选择器 | |
| `json` / `yaml` / `markdown` / `textarea` | 编辑器 | |
| `editor` | 代码 | `language` |
| `model_select` | 模型 | `model_type` 默认 `"llm"`；**3.0 起产出值是 `provider_id:内部ID`**（旧配置值由框架按 legacy_ids 自动规范化） |
| `persona_select` | 人格 | |
| `section` | 分组 | `collapsed`, `fields: {...}` |
| `info` | 只读说明 | `level`；**不存配置值** |

> 迁移示例：`{"type":"enum","options":[...]}` → `{"type":"string","options":[...]}`；动态会话多选 `{"type":"multi_select","source":"session","allow_custom":true}`；单会话 `{"type":"session_select"}`。

配置合并规则（`_ensure_plugin_config`）：
- 顶层字段缺失 → 写入 `default`
- `section` 缺失或非 dict → 建 `{}`，再补子字段 default
- **已有键不会被 default 覆盖**（用户改过的值保留）
- 未知 type 不报错，静默当 string 处理；`0` 是合法整数，读配置用 `if v is not None` 判断，勿用 `or 默认值`

### 6.2 section 读取方式

```json
{
  "section_basic": {
    "type": "section",
    "name": "基础",
    "collapsed": false,
    "fields": {
      "enabled": { "type": "switch", "name": "启用", "default": true },
      "api_key": { "type": "sensitive", "name": "Key", "default": "" }
    }
  }
}
```

```python
basic = cfg.get("section_basic", {})
self.enabled = basic.get("enabled", True)
self.api_key = basic.get("api_key", "")
```

**始终** `cfg.get(key, default)`，避免缺配置崩溃。

### 6.3 模型/会话选择值的 3.0 语义（重要）

- `model_select` / `multi_select(source="model")`：3.0 起存的值是 `provider_id:内部ID`（uuid 形态）——插件拿到值直接传给 `ctx.get_llm_client(...)` 即可，**不要展示给用户看**（uuid 乱码），展示用 §3.4 的 `model_name` 解析。
- 如果你做**文本型**模型输入框（用户手填），用户必然按习惯填「提供商:可读名」——框架不会替你解析新模型的可读名，必须按 §3.4 的 `_resolve_display_ref` 模式自己反查兜底。
- `session_select` / `multi_select(source="session")`：值是路由 sid（`adapter:type:id`），不是 `Session.internal_id`。

---

## 7. 日志 / 路径 / 网络

```python
from core.plugin import logger  # 或
from core.logging_manager import get_logger
logger = get_logger("my_plugin", "cyan")  # info/warning/error/exception/debug

from core.utils.path_utils import get_data_path, get_config_path
get_data_path()    # data/
get_config_path()  # data/config/

from core.utils.network import download_file, get_file_content
await download_file(url, local_path)
data = await get_file_content(url)  # 直接取 bytes
await download_file(url, local_path, max_bytes=50*1024*1024)  # 超限抛 ValueError
```

---

## 8. Adapter 操作（谨慎）

```python
adapter = self.ctx.adapter_mgr.get_adapter("qq")  # 或 event.adapter.name
client = adapter.get_client()                     # QQ(OneBot) 适配器保留 get_client()
# OneBot/NapCat 常见：
await client.send_action("get_group_member_list", {"group_id": 123})
await client.send_action("send_group_msg", {"group_id": 123, "message": [...]})
await client.send_action("send_forward_msg", {...})
```

**注意**：`send_action` 名称与参数因适配器而异。非 NapCat 必须查对应 adapter 源码。
通用发送优先用：

```python
await self.ctx.send_message_chain(sid, chain)
# 或能力对象：adapter.get_capability(IMCapability) → im.send_group_message / send_direct_message
```

**Feed（动态/评论）能力**——没有 `get_client()`/`send_action`，全异步接口：

```python
from core.adapter import FeedCapability, FeedQuery

adapter = self.ctx.adapter_mgr.get_adapter("bilibili")  # 或 event.adapter.name
try:
    feed = adapter.get_capability(FeedCapability)
except ValueError:
    return "当前适配器不支持动态/评论"

page = await feed.get_feed(FeedQuery(count=10))        # FeedPage(items/next_cursor/has_more)
hits = await feed.search_feed(FeedSearchQuery(keyword="关键词", count=5))
await feed.send_comment(MessageChain([Text("回复内容")]), target, root=cmt_id, parent=None)
await feed.send_post(FeedPost(content=MessageChain([Text("发动态")]), extra={...}))  # 平台特有参数走 extra
```

---

## 9. 状态管理与计数（实战必读）

### 9.1 反模式

```python
# ❌ 命中后整状态 pop，计数永远是 0
self.count[sid] += 1
self._clear_all(sid)  # 内部 pop 了 count
logger.info(self.count[sid])  # defaultdict → 0

# ❌ defaultdict(asyncio.Task) 会在访问缺失 key 时构造非法 Task
self.tasks = defaultdict(asyncio.Task)

# ❌ 只增不减的 max 计数，用户回来后永久卡死
```

### 9.2 推荐模式

```python
self.count: dict[str, int] = {}          # 或 defaultdict(int)
self.tasks: dict[str, asyncio.Task] = {} # 普通 dict

def clear_window(self, sid, keep_count=False):
    self.until.pop(sid, None)
    if not keep_count:
        self.count.pop(sid, None)
    t = self.tasks.pop(sid, None)
    if t and not t.done():
        t.cancel()

# 命中：+1，关窗但保留 count
self.count[sid] = self.count.get(sid, 0) + 1
self.clear_window(sid, keep_count=True)

# 用户真实唤醒/发言：重置 count
self.count[sid] = 0

# 达上限：不再开窗
if max_n != -1 and self.count.get(sid, 0) >= max_n:
    return
```

### 9.3 后台任务

```python
async def initialize(self):
    self._task = asyncio.create_task(self._loop())

async def terminate(self):
    if self._task and not self._task.done():
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

async def _loop(self):
    try:
        while True:
            await self._tick()
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("bg error")
```

---

## 10. 实用模式

### 10.1 唤醒词 + 缓冲（对齐内置 chat 插件）

```python
@on.im_message(priority=Priority.HIGH)
async def handle_msg(self, event: KiraMessageEvent):
    for m in event.message.chain:
        if isinstance(m, Text) and any(w in m.text for w in self.waking_words):
            event.message.is_mentioned = True
            break

    if not event.is_mentioned:
        if self.receive_unmentioned:
            buf = self.ctx.get_buffer(str(event.session))
            if buf.get_length() >= self.max_unmentioned:
                buf.pop(count=buf.get_length() - self.max_unmentioned + 1)
            event.buffer()
        else:
            event.discard()
        return

    event.buffer()
    sid = event.session.sid
    if self.ctx.get_buffer(sid).get_length() + 1 >= self.max_buffer:
        event.flush()
        return
    # 否则 debounce 后 flush（见内置 chat 插件）
```

### 10.2 过滤机器人自己的私聊回声

```python
if not event.is_group_message():
    self_id = str(event.message.self_id or "")
    sender_id = str(event.message.sender.user_id) if event.message.sender else ""
    if self_id and sender_id and self_id == sender_id:
        event.discard()
        return
```

### 10.3 跨插件

```python
other = self.ctx.get_plugin_inst("other_plugin_id")
if other:
    await other.some_public_method(...)
```

### 10.4 持久化

```python
data_dir = self.ctx.get_plugin_data_dir()
path = data_dir / "state.json"
path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
```

### 10.5 会话能力 / 语言 / 时区

```python
# 会话级能力覆盖（合并全局 bot_config.capabilities + 会话覆盖）——⚠️ 3.0 起异步
caps = await self.ctx.get_session_capabilities(sid)
# 例如 caps.get("image_generation", {}).get("enabled", True)

lang = self.ctx.get_lang()    # 'zh' / 'en'
tz = self.ctx.get_timezone()  # ZoneInfo | None，None 时回退 datetime.now()
```

**同步钩子/读点想读能力（3.0 适配模式）**：3.0 起 `get_session_capabilities` 是异步。如果业务在必须保持同步的钩子里（结构不变量「零 await」），用「TTL 缓存 + 异步预热」模式：同步读点只读缓存；异步入口（消息到达等）到点 `await` 预热；冷缓存返回与旧异常路径一致的兜底值，零 RuntimeWarning（用 `inspect.isawaitable` 探测 + `close()` 未用 coroutine）。

### 10.6 内置 agent 插件与文件发送策略

- 内置 **`agent`** 插件（`core/plugin/builtin_plugins/agent/main.py`）提供 `read_file` / `write_file` / `edit_file` / `list_files` / `grep` / `search_files` / `exec`（`manage_background_exec` 随 `exec` 启用）；配置分 `tools` / `file_access` / `exec_access` 三段，会话权限模式为 `allow_list` / `deny_list` + `session_list`。
- `read_file` 能处理**图片**（按会话 `image_recognition.mode`：原生多模态返图，或 VLM 描述）与**音频**（默认 STT 转写）。
- `<file>` 标签**不再无条件放行绝对路径**：仅 `data/files`、`data/temp` 对所有会话开放；`~/.ssh`、`.pem`、`key`、`token`、`secret` 等受限关键字一律拒绝；agent 的 `extra_read_paths` 额外放行但需通过其 `file_access` 会话名单。
- **插件自己转发本地文件时，请把产物写到 `data/files` 或 `data/temp`**，否则可能被策略拦下。

### 10.7 WebUI 内置聊天（webchat）

- 路由 sid `webchat:dm:admin`，管理员在网页直接与 Kira 对话（文字/图片/文件）。
- 它走完整消息链路：你的钩子、工具、记忆插件对它**自动生效**，无需任何特判。
- 附件上限 10 个 / 20 MiB；文字 ≤16000 字符；文件工具默认开、命令执行默认关。
- 清空网页侧聊天记录 ≠ 清空 LLM 上下文（后者走 `update_session(sid, content=[])`）。

---

## 11. LLM XML 输出（框架解析）

```xml
<msg>
  <text>你好</text>
  <image url="https://..."/>
  <at pid="12345"/>
</msg>
```

内置标签：`text/img/at/reply/forward/emoji/record/file/video/poke/json`
自定义：`@register.tag`；根标签 `parent=None` 与 `<msg>` 同级。

> 3.0 起图片输出标签统一为 `img`（历史存档里的元素类型是 `image`，两者不同，见 §1.2）。

空消息停止判断示例：

```python
import re
def is_empty_msg(xml: str) -> bool:
    return bool(re.match(r'^\s*<msg\s*/>\s*$|^\s*<msg>\s*</msg>\s*$', xml or ""))
```

---

## 12. 开发规范与常见陷阱（浓缩）

1. Hook 按上表签名写，并加 `*_`；Tool 首参 `event`，其余关键字=schema。
2. **`initialize` 失败则工具/钩子不注册**；`terminate` 必须可重入。
3. 不阻塞事件循环：I/O `await`，CPU `asyncio.to_thread()`。
4. task 用普通 `dict`，禁止 `defaultdict(asyncio.Task)`。
5. `ON_LLM_RESPONSE` 过滤 `resp.tool_calls`。
6. `ToolSet.tools` 是 **BaseTool 实例**，用 `.name` / `.remove()`，禁止当 dict。
7. 合成事件：群聊必须 `group=`；之后覆盖 `event.session`；注入走 `ctx.event_bus.publish(event)`。
8. 单条事件用 `event.session.sid`，Batch 才有 `event.sid`。
9. schema 浮点用 `float` 不是 `number`；section 嵌套读取。
10. 计数：关窗 ≠ 清计数；用户真实交互时重置 max 计数。
11. **`@on.final_result` 整轮触发一次**（`(event, KiraFinalResult)`）；`event.stop()` 不能撤回已发消息。
12. `get_plugin_data_dir()` 在插件自身代码中调用。
13. 钩子异常尽量自捕；框架也会捕获并触发 `ON_EXCEPTION`。
14. 敏感配置用 `sensitive`；日志勿打 Token/密码。
15. **不要臆造** `ctx.db` 方法、adapter action、未文档字段。
16. 读 `req.user_prompt` 先过滤 `persist=False`（含 `memory` 段）；挪 Prompt 动原对象保留 kwargs（否则 `{time_str}` 不格式化）。
17. **会话 API 全异步**（§3.2）：读快照改完必须显式 `update_session`；清空用 `content=[]` 保元数据；批量读列表用 `get_sessions(include_content=False)`。
18. **模型身份分离**（§3.4）：展示用 `model_name`，引用用内部 ID；文本型配置要做显示名反查兜底；Provider 停用会抛 `ProviderAPIError`。
19. **模块导入走包级**（`from core.plugin import ...`）；`core.plugin.plugin_registry`/`plugin_handlers`、`core.utils.model_clients`、旧适配器基类（`adapter_utils`）都已删除。
20. **平台判断改能力查询**：IM 用 `get_capability(IMCapability)`，动态/评论用 `FeedCapability`；不要按适配器类型判断能否聊天。
21. **事件字段 `supported_elements`**（旧名 `message_types` 兼容别名）；图片输出标签 `img`、历史元素类型 `image`。
22. **`KiraCustomEvent`/`KiraCommentEvent` 是单处理器事件**：勿 `event_bus.subscribe`；用 `@on.custom_event(event_name=...)` / `@on.comment` 钩子。
23. **MCP 工具由框架自动并入 tool_set**，插件勿手动注册；查询状态用 `ctx.mcp_mgr`；Skills 状态用 `ctx.skills_mgr`。
24. **新代码注释一律英文**（AGENTS.md 规则）；能力优先 `@register.tool` / `@register.tag`，勿用命令语法。
25. **工具返图给主模型用 `ToolResult(media_refs=[...])`**（配 `store_session_media`），**禁止**自己在 tool 消息里塞 `image_url`；`attachments` 是「让模型用 `<file>` 发送附件」的旧通道，用途不同。
26. **插件页面/静态资源以 `Cache-Control: no-store` 提供**：更新插件后无需清浏览器缓存。
27. **内置 `agent` 插件**管文件/命令工具，`<file>` 标签只放行 `data/files`、`data/temp`（+ 额外授权路径）；产物写到这两个目录。
28. **记忆裁剪**：`bot_config.bot.memory_overflow_discard_count` 控制溢出多丢几块；`session_memory_updated` 事件多带 `discarded_memory`。
29. **`req.messages` 是 `OpenAIMessage`（pydantic）**，勿当裸 dict 用；`LLMResponse` 用 `input_tokens/output_tokens/cached_tokens`。
30. **同步读会话能力的钩子**：3.0 异步化后用「TTL 缓存 + 异步预热」模式（§10.5），别在零-await 不变量的钩子里硬 await。

---

## 13. 插件测试清单

- [ ] `manifest.plugin_id` = 目录名；`core_version` 只有下界（不写 `<3.0` 这类上界）
- [ ] manifest 完整（display_name/version/author/description；可选 repo/locales/tags/icon）
- [ ] `schema` 字段均有 `type`/`name`；浮点用 `float` 非 `number`；无已废弃 `enum`
- [ ] `__init__` 配置有默认值；section 嵌套正确
- [ ] `initialize` 成功路径清晰；失败不会半注册
- [ ] `terminate` 可重入；热重载不泄漏 task
- [ ] 工具签名与 schema 一致；方法名可被 `getattr` 绑定
- [ ] Hook 签名与上表一致，并兼容 `*_`
- [ ] 若用 `llm_response` 做业务，已跳过 `tool_calls` 步
- [ ] 若改 `tool_set`，按 BaseTool API
- [ ] 合成消息：群聊带 `group`，覆盖 `session`，注入走 `event_bus.publish`
- [ ] 单条用 `event.session.sid`，Batch 用 `event.sid`
- [ ] **会话读写全部 `await`**（get_session/update_session/update_memory/delete_session/get_effective_capabilities/update_session_capabilities/get_session_capabilities）；清空用 `update_session(sid, content=[])`
- [ ] **模型展示用 `model_name`**（`getattr(info,'model_name',None) or model_id`）；自定义 Provider 发上游用 `model_name`；文本型模型配置有显示名反查兜底
- [ ] **导入全包级**，无 `plugin_registry`/`plugin_handlers`/`core.utils.model_clients`/旧适配器基类残留
- [ ] 平台专有逻辑已按 `adapter.platform`/`name` 筛选；IM 走 `IMCapability`，动态/评论走 `FeedCapability`
- [ ] 生产事件用 `supported_elements=`（或按构造签名分流）
- [ ] 计数/状态在命中、超时、用户打断、达 max 时行为正确
- [ ] 读 `req.user_prompt` 已过滤 `persist=False`（含 `memory` 段）
- [ ] 若工具返图：用 `ToolResult(media_refs=[...])` + `store_session_media`，未在 tool 消息里塞 `image_url`
- [ ] 若用 `@on.final_result`：按 `KiraFinalResult.step_results` 处理，且知道 `stop()` 不能撤回已发消息
- [ ] 产物文件写到 `data/files` 或 `data/temp`
- [ ] 注释为英文
- [ ] `requirements.txt` 完整
- [ ] 语法：`python -m py_compile main.py`

---

## 14. 相关源码索引（需要细节时向用户索要）

| 路径 | 内容 |
|------|------|
| `core/plugin/base.py` | BasePlugin |
| `core/plugin/plugin_context.py` | PluginContext（完整注入面/发送/缓冲/能力/注册） |
| `core/plugin/handlers.py` | EventType、Priority、event_handler_reg |
| `core/plugin/decorators.py` | register/on 装饰器 |
| `core/plugin/manager.py` · `metadata.py` · `registry.py` | PluginManager · PluginInfo · 注册表（`_plugin_components`） |
| `core/plugin/pages.py` · `components.py` · `store.py` | PluginPage/PageMenu · 组件类型 · 商店 |
| `core/plugin/builtin_plugins/chat/main.py` | 官方默认聊天/缓冲参考 |
| `core/plugin/builtin_plugins/agent/main.py` | 文件/命令 agent 插件（file_access / exec_access 权限） |
| `core/plugin/builtin_plugins/comment/main.py` | 默认评论回复插件（@on.comment 范例） |
| `core/plugin/builtin_plugins/kira-ai/{tags.py,file_send_policy.py}` | 标签实现 + `<file>` 文件发送策略 |
| `core/chat/message_utils.py` | 事件、MessageChain、KiraCustomEvent（含 `message_types` 兼容别名） |
| `core/chat/message_elements.py` | 消息元素 |
| `core/chat/session.py` · `session_manager.py` | Session（content/data/flatten_content）、全异步会话接口 |
| `core/chat/message_history.py` · `session_buffer.py` | 结构化消息历史 · SessionBuffer |
| `core/message_manager.py` | MessageProcessor（仅剩转发/兼容入口） |
| `core/workflow/src/im/{workflow,context,stages/*}.py` | 3.0 IM 阶段管线（Receive/Route/PrepareBatch/BuildRequest/AssembleRequest/ExecuteAgent/Finalize） |
| `core/workflow/src/im/message_delivery.py` · `message_formatter.py` | 发送+parse_xml/add_message_ids · format_to_text |
| `core/provider/llm_model.py` | LLMRequest/Response、OpenAIMessage |
| `core/provider/provider.py` · `provider_manager.py` | BaseProvider/ModelInfo · ProviderManager（get_models/get_model_info/get_model_client/register_model；停用检查） |
| `core/provider/openai_compatible.py` | OpenAICompatibleLLM/TTS/STTClient（公共客户端） |
| `core/provider/model_identity.py` · `model_migration.py` | 内部 ID 生成/resolve_model_entry/legacy_ids · 配置迁移 |
| `core/agent/tool.py` | ToolSet、ToolResult |
| `core/utils/tool_utils.py` | BaseTool |
| `core/agent/agent_executor.py` | Agent 循环、ON_LLM_RESPONSE 时机 |
| `core/agent/func_tool_manager.py` | FuncToolManager：register_tool / build_tool_set / execute_tool |
| `core/agent/mcp_mgr.py` · `skills_mgr.py` | MCP 管理器 · Skills 系统 |
| `core/agent/message.py` | OpenAIMessage（pydantic，`extra`/`llm_message_id` 身份） |
| `core/utils/common_utils.py` | text_to_speech / speech_to_text / generate_image / image_to_image / desc_img / image_to_base64 |
| `core/utils/media_refs.py` | 工具返图引用：store_session_media / resolve_media_reference |
| `core/utils/image_compression.py` | compress_image_element / compress_image_file |
| `core/utils/path_utils.py` | get_data_path / get_config_path |
| `core/prompt_manager.py` | Prompt |
| `core/prompts/agent_tmpl.py` | 系统 prompt 模板名 |
| `core/config/config_field.py` | schema 字段类型 |
| `core/adapter/base.py` · `context.py` · `capabilities.py` | BaseAdapter/AdapterContext/能力表（IMCapability/FeedCapability） |
| `core/adapter/message_format_metadata.py` | MessageFormatMetadata（supported_elements/emojis） |
| `core/adapter/access.py` | ListAccessPolicy（权限名单） |
| `core/adapter/adapter_registry.py` | AdapterManager.get_adapter |
| `core/adapter/builtin/webchat/` | 内置网页聊天适配器（webchat:dm:admin） |
| `core/persona/persona_manager.py` · `model.py` | 人设（参考图/场景规则） |
| `core/event_bus.py` | 事件订阅（KiraCommentEvent/KiraCustomEvent 为单处理器，勿订阅） |
| `core/tag/` | 标签系统 |
| `core/db/service.py` · `db/mixins/` | DatabaseService（业务 mixin：sessions/personas/stickers/image_cache/telemetry 等） |
| `core/db/migrate_to_db.py` | 旧 JSON → SQLite 迁移（含 chat_memory.json 导入） |
| `core/config/default.py` | VERSION 常量与默认配置 |

---

## 15. 数据库 self.ctx.db（仅列公开能力）

`DatabaseService` 内部拆成业务 mixin（`core/db/mixins/`），插件仍统一用 `self.ctx.db`。已知方法族（全异步）：

- 贴纸：add/get/list/update/delete_sticker
- 图片描述缓存：add/get/update/delete_image_desc_cache、cleanup_expired_image_desc_cache
- 人格：add/get/update/delete/list_persona、set/get_active_persona
- 会话：`SessionManager` 已接管会话持久化，**插件会话读写走 `ctx.session_mgr`（§3.2），不要直查 db 的会话表**
- 插件商店源：add/get/get_by_url/list/update/delete_plugin_store_source
- 遥测：add_telemetry_message / add_telemetry_llm_usage / 查询与标记上报——一般插件不需要

**业务数据优先写 get_plugin_data_dir() 或自建 sqlite**，不要滥用框架 DB 表。

---

## 16. 必须向用户索要的场景

1. 具体 adapter 的 send_action 名与参数（非通用 OneBot）
2. self.ctx.db 未列出的方法细节
3. 新增 Provider 实现（core/provider/src/，或插件自带 Provider 的 schema 结构）
4. WebUI 复杂前端约定 / JWT 鉴权细节
5. 项目私有封装、自定义事件 payload
6. 第三方平台特殊 API

**原则**：通用逻辑直接写；不确定的框架内部细节先问再写。

---

## 附录 A：2.x 差异速查（需要双世代兼容时）

> 新插件按正文写即可（面向 3.0）。如果你的用户群还在 2.x（如 v2.34.8），用**特征识别**（`hasattr` / `inspect.isawaitable` / try-import 候选链 / 签名探测）做双世代，**严禁写 `if version >= "3.0"` 这类版本绑定**。

### A.1 会话 API（最大差异）

| 操作 | 2.x（同步） | 3.0（异步） | 双世代写法 |
|------|------------|------------|-----------|
| 读拍平 | `sm.fetch_memory(sid)` | `(await sm.get_session(sid, ensure_session=False)).flatten_content()` | `hasattr(sm, "fetch_memory")` 分流 |
| 读分块 | `sm.read_memory(sid)` | `(await sm.get_session(sid)).content` | 同上 |
| 写覆盖 | `sm.write_memory(sid, chunks)` | `await sm.update_session(sid, content=chunks)` | 同上 |
| 追加块 | `sm.update_memory(sid, chunk)` | `await sm.update_memory(sid, chunk)` | 有同名但 3.0 异步 → `inspect.isawaitable(res)` |
| 计数 | `sm.get_memory_count(sid)` | `len((await sm.get_session(sid)).content)` | 同上 |
| 列表 | `sm.get_session_info()` | `await sm.get_sessions(include_content=False)` | `hasattr(sm, "get_session_info")` |
| 标题/描述 | `sm.update_session_info(...)` | `await sm.update_session(...)` | 同上 |
| 删除 | `sm.delete_session(sid)` | `await sm.delete_session(sid)` | `res=...; if isawaitable: await` |
| 能力 | `sm.get_effective_capabilities` / `update_session_capabilities` / `ctx.get_session_capabilities(sid)` 全同步 | 同名全异步 | `res = fn(...); (await res) if inspect.isawaitable(res) else res` |
| 内部缓存 | `sm.chat_memory` dict 直读 | **已删**（SQLite） | 需要只读快照的同步链路：2.x 直读 dict；3.0 用「异步入口预热镜像」（见 A.5） |

**清空上下文**（两代都保元数据）：

```python
async def clear_context(sm, sid):
    if hasattr(sm, "write_memory"):           # 2.x
        sm.write_memory(sid, [])
    else:                                     # 3.0
        await sm.update_session(sid, content=[])
```

### A.2 模型身份

| 项 | 2.x | 3.0 |
|----|-----|-----|
| `model_id` 语义 | 即可读名 | 内部稳定 ID（uuid 形态） |
| 可读名 | = model_id | `model_name` |
| 展示 | `info.model_id` | `getattr(info, "model_name", None) or info.model_id` |
| 引用 `pid:mid` | 冒号后 = 可读名 | 冒号后 = 内部 ID |
| Provider 客户端 | `core.utils.model_clients` | `core.provider.openai_compatible`（try-import 候选链） |
| `register_model(pid, type, name, cfg)` | 返回 None | 返回内部 ID |

### A.3 插件模块路径

```python
try:    # 3.0
    from core.plugin.handlers import event_handler_reg, EventType
except ImportError:  # 2.x
    from core.plugin.plugin_handlers import event_handler_reg, EventType
```

`PluginContext` 3.0 新增必填字段（`prompt_mgr`/`skills_mgr`/`mcp_mgr`/`message_history`/`image_desc_cache`/`session_buffer_mgr`/`message_delivery`）——测试桩构造按签名探测填充；`sticker_manager` 在 3.0 是只读别名（规范名 `sticker_mgr`）。

### A.4 适配器与事件

| 项 | 2.x | 3.0 |
|----|-----|-----|
| 适配器抽象 | `adapter_utils.py` 的 `IMAdapter`/`SocialMediaAdapter`/`LiveStreamAdapter` 继承 | `BaseAdapter` + 能力对象（`get_capability`） |
| 发送 | `adapter.send_group_message` | 能力对象 `IMCapability.send_group_message`（QQ 适配器仍保留委托方法兜底） |
| 事件字段 | `message_types=` | `supported_elements=`（按 `inspect.signature(KiraMessageEvent.__init__)` 分流） |
| 表情目录 | `adapter.emoji_dict` | `await im.get_message_metadata()` 的 `emojis` |
| 动态/评论 | `SocialMediaAdapter.get_feed/search/send_comment` | `FeedCapability` 全异步接口 |

### A.5 消息处理内部接口

| 旧入口（2.x） | 3.0 位置 | 双世代注意 |
|---------------|----------|-----------|
| `MessageProcessor.message_format_to_text` | `MessageFormatter.format_to_text`（经 `mp.im_workflow.ctx.message_formatter` 可达） | 逐层 `getattr` 探测 |
| `MessageProcessor._parse_xml_msg` / `_add_message_ids` | `MessageDeliveryService.parse_xml` / `add_message_ids`（静态方法） | `ctx.message_delivery` 直达 |
| `MessageProcessor.send_xml_messages` | **已删**（XML 由 ExecuteAgentStage 协调） | 猴补丁类插件改包 `MessageDeliveryService.send_message_chain`（按链对账） |
| `mp.min_message_delay` | `MessageDeliveryService.min_message_delay` | `getattr(ctx, "message_delivery", None) or mp` |
| `mp.skills_manager` / `mp.mcp_manager` | `ctx.skills_mgr` / `ctx.mcp_mgr` | 先新后旧探测 |
| 注入合成消息 | `mp.handle_im_message(event)` | `await ctx.event_bus.publish(event)` |

**同步链路只读会话（镜像模式）**：若你的同步内部函数族（如合并引擎）在 3.0 无法 await——2.x 直读 `chat_memory` dict；3.0 在异步入口（消息钩子/命令/API）先 `await sm.get_sessions()` 预热一个 sid→meta 镜像（TTL 1–2s 节流），同步链路只读镜像；写入后失效镜像；线程区（`asyncio.to_thread`）的写入放延迟队列由异步方冲刷。

---

*本指南目标：Agent 仅凭此文档即可开发标准 KiraAI 插件；遇未覆盖内部实现时向用户索要源码，禁止臆造。*
