# KiraPhone 交互动效规格

> 历史设计资料：包含早期方案和待办，不能作为当前功能已验证的依据。2026-10-20 修复以后，隐私开关、连接过渡及验收状态以 CODE-REVIEW.md、VALIDATION.md 和当前源码为准。

> 依据技能：Advanced Interaction Design（10 种交互动效模式）。
> 事实来源：`uni-app/pages/index/index.uvue`、`components/SwipeDeck.uvue`、`components/SpeedWheel.uvue`、`components/ProgressRing.uvue`、`components/FeedbackButton.uvue`；参数以代码为准。
> 原则：先判断「变化从哪开始、操作在哪结束、这次变化需要谁跟随、周围需要让位吗」，再选模式；不硬套、不堆模式。

---

## 0. 结论速览

| 场景 | 选定模式 | 结论 |
|---|---|---|
| 底部四页签切换 | **Expanding Tag Selection / 标签挤开** | 采用；只做指示器拉长，相邻页签让位待补 |
| 步骤卡横滑（SwipeDeck） | **Velocity-Based Slider Snap / 滑杆惯性吸附** | 采用；已实现速度投射 + 阻尼吸附 + 边界回弹 |
| 动画速度滚轮 | **Velocity-Based Slider Snap**（同模式第二实例） | 采用；垂直刻度版，磁吸阈值 18px |
| 偏好勾选 + 进度环 | **Staggered Bulk Selection / 批量勾选错峰**（主）+ **Spring Stepper Progress / 步骤条回弹**（环） | 环已采用；列表已补 40ms 错峰 |
| 连接准备时间线 | **Spring Stepper Progress** | 部分采用；缺超调，当前是线性过渡 |
| 防截屏开关 | **Ripple Feedback for Related Switches / 开关联动反馈** | 采用；单开关版本，涟漪从开关中心起 |
| 「这台手机」叠卡 | **Stacked Card Scroll / 卡片堆叠滚动** | 形态采用；当前由点击驱动，不是滚动驱动 |
| 连接成功反馈（收圆 + 勾 + 粒子） | **不套用** | 模式库不覆盖单按钮成功微交互，保留自定义 |
| 步骤详情面板扩张 | **不套用** | 本质是覆盖层接管，不属 10 种布局型交互 |
| 侧边抽屉 | **不套用** | 抽屉滑入不在模式库；保持现状 |

---

## 1. 判断过程（按技能四问）

| 判断 | 本 App 的答案 | 指向 |
|---|---|---|
| 变化应该从哪里开始？ | 页签点击从手指位置起涟漪；步骤卡从卡片自身扩张 | Expanding Tag Selection、局部涟漪 |
| 操作最后应该停在哪里？ | 卡片停在落点、滚轮停在刻度、详情缩回卡片 | Velocity-Based Slider Snap、Stacked Card Scroll |
| 这次变化需要谁跟着回位？ | 页签相邻项、勾选项、时间线分段 | Staggered Bulk Selection、Spring Stepper Progress |
| 周围内容要不要一起让位？ | 页签胶囊拉长时相邻页签不让位（当前缺口） | Expanding Tag Selection |

主导交互（每屏只有一个）：首页 = 卡片横滑吸附；偏好页 = 勾选 + 环；设置页 = 表单（无动效）；关于页 = 静态。

---

## 2. 逐项规格

### 2.1 底部页签切换

**Selected interaction**
Expanding Tag Selection / 标签挤开（主）；Ripple Feedback 的局部涟漪作为附带反馈。

**Why this fits**
变化从被点的页签开始，胶囊先横向拉长、再回弹到新位置，和「选中项扩张、邻居让位」的标签选择是同一类问题；页面本身不应缩放或闪白。

**Interaction behavior**
- 触发：点击底部任一枚页签，或从抽屉/步骤卡跳转。
- 开始：被点页签出现半径 96px 的淡青圆（`rgba(23,102,92,0.17)`），同时胶囊以 1.32 倍横向拉长，`transform-origin: center`。
- 过程：胶囊在 140ms 内保持拉伸并平移到新页签；页面内容立即切换，不做缩放；涟漪 300ms 内从 `scale(0.22)` 扩散到 1、透明度 0.9→0。
- 结束：胶囊在 380ms 内从 1.32 回落到 1，曲线带轻微过冲（`cubic-bezier(0.34,1.56,0.64,1)`）；涟漪 350ms 时移除。
- 取消/失败：目标页与当前页相同时只播涟漪，不拉长胶囊。
- 触控区：页签高 64px，整格可点；涟漪不拦截点击（`pointer-events: none`）。
- 与技能要求的一致点：反馈=状态变化，不是装饰；不一致点：相邻页签没有让位，胶囊拉长时会轻微盖住两侧文字。

**Copyable prompt**
Create an expanding tab-selection interaction in an existing bottom tab bar. When the user taps a tab, grow the sliding indicator horizontally to 1.32× for 140 ms around its center while it translates to the newly selected tab, then settle back to 1× with a 380 ms spring curve that overshoots slightly. Switch the page content immediately, without scaling or fading the page. At the tap point, expand a 96 px-radius translucent ripple in the accent color from scale 0.22 to 1 and fade it from 0.9 to 0 opacity over 300 ms, then remove it; the ripple must not intercept touches. Keep each tab a 64 px-tall hit target, preserve the existing labels and icons, do not let the stretched indicator cover neighboring labels, support touch and keyboard activation, and fall back to an instant switch when reduced motion is enabled or effects are turned off.

**落地差距**
- P1：胶囊拉长时挤压相邻页签的图标/文字（当前直接覆盖）。
- P2：补 `prefers-reduced-motion` 与「涟漪反馈」开关的联动说明（开关已有，系统设置未接）。

---

### 2.2 步骤卡横滑 / 动画速度滚轮

**Selected interaction**
Velocity-Based Slider Snap / 滑杆惯性吸附（同一模式的两个实例：横向卡片、垂直刻度轮）。

**Why this fits**
两者都是「拖到某处、松手后由速度决定落点」，且都需要边界限制与过冲回弹；模式要求的「拖动跟手、松手投射、吸附目标、超出回弹」与现有实现一一对应。

**Interaction behavior**
- 触发：在步骤卡区域横拖，或在速度 sheet 的滚轮上纵拖。
- 开始：手指按下即进入跟手，`transition-duration: 0`；卡片按拖动速度产生轻微倾斜与横向拉伸（`lean` 限制 ±6°，`scaleX` 最多 1.17），滚轮每行 56px 跟随。
- 过程：手指移动时位移 1:1；越过首/末边界时按 0.3 阻尼（卡片）或 0.35（滚轮）衰减；滚轮在距最近刻度 18px 内被额外吸入 34%。
- 结束：松手按速度投射目标位置；卡片用 460ms 阻尼余弦 `target - distance·e^(-6.4p)·cos(1.5πp)` 吸附，滚轮用 560ms `e^(-5.4p)·cos(2.6πp)`，末端自然回弹。
- 取消/失败：位移不足阈值（卡片 20% 宽度或 0.5px/ms，滚轮未过半个刻度）回弹到原位置；回弹 440–460ms，不锁死后续手势。
- 触控区：卡片整卡可拖；滚轮行高 56px，上下各留半行空白，避免误触页签。
- 数据与状态：卡片落点决定 `step` 与时间线填充；滚轮落点决定保存的 `animationSpeed`。视觉位置永远由数据回算，不在动画中直接改数据。

**Copyable prompt**
Create a velocity-based snap interaction for two existing components: a horizontal card deck and a vertical tick wheel. On pointer or touch start, stop all transitions and move the content 1:1 with the finger. Track velocity over the last few moves. While dragging, tilt and stretch the active card up to 6° and 1.17× horizontal scale in proportion to speed, and resist movement beyond the first and last item with 0.3 damping; for the wheel, apply a magnetic pull toward the nearest tick within 18 px. On release, project the landing target from velocity, clamp it to the available range, and animate to it with a damped-cosine settle (about 460 ms for cards, 560 ms for the wheel) that ends with a subtle overshoot. If the drag stays under 20% of the width or 0.5 px/ms, spring back to the current item in about 460 ms. Keep the card fully draggable and the wheel rows 56 px tall, preserve the existing tick labels and per-card content, update the selected index only on settle, support touch and mouse, and disable overshoot when reduced motion is enabled.

**落地差距**
- 已满足：跟手、速度投射、阻尼吸附、边界阻尼、数据回算。
- P2：滚轮的「半格吸附」只在松手时生效，拖动中无逐格顿挫；如需要可加 `pointermove` 阈值反馈。

---

### 2.3 偏好勾选 + 进度环

**Selected interaction**
Staggered Bulk Selection / 批量勾选错峰（主）+ Spring Stepper Progress / 步骤条回弹（进度环）。

**Why this fits**
勾选是「一次改多项状态」，模式要求列表逐项错峰、勾号有轻微弹性；进度环是「完成度向前跳一格再回弹」，两种模式在同屏互补。

**Interaction behavior**
- 触发：点总开关或任一子项；总开关在部分选中时显示 `–`。
- 开始：被点的勾选框立即变实心并弹一下（`scale` 0.2→1，180ms，带回弹）；总开关状态在下一帧同步。
- 过程：进度环 14 个点按新完成数逐个点亮，每点延迟 14ms，背景色 240ms 过渡；中心数字用 460ms `easeOutCubic` 滚动到新值，数字条按 38px 行距位移。
- 结束：顶部概览卡底色在 3 档之间过渡；环与数字在勾选后 460ms 内追平，不阻塞再次点击。
- 取消/失败：从全选取消一项时，环从 14 点回退到对应数量，数字反向滚动；总开关变半选 `–`。
- 触控区：整行 64px 可点（不只勾选框），总开关行与子项行一致。
- 与技能要求的一致点：状态即时更新、动画只做视觉确认；已补上 40ms 级别的列表错峰，勾选从总开关到三项依次落位。

**Copyable prompt**
Create a staggered bulk-selection interaction for a four-row settings list with a master toggle. When the user checks or unchecks a row, update the underlying selection state immediately and animate a filled checkmark scaling from 0.2 to 1 with a small overshoot in 180 ms. When several rows change at once, stagger their checkmarks by about 40 ms in reading order so the change reads as a batch rather than one repaint. Feed the selected count into a 14-dot progress ring: light the dots in order with a 14 ms stagger and a 240 ms color transition, and roll the central number to the new value with a 460 ms ease-out over a vertical digit strip. Show a partial state on the master row when only some items are selected. Keep each row a 64 px hit target, preserve the existing toggle semantics and labels, update data before visuals, and skip the stagger and overshoot when reduced motion is enabled.

**落地差距**
- 已实现：列表勾选 `transitionDelay = index * 40ms`，视觉确认不阻塞状态写入。
- P2：`ProgressRing` 的数字滚动在系统减少动效时应直接跳值。

---

### 2.4 连接准备时间线

**Selected interaction**
Spring Stepper Progress / 步骤条回弹。

**Why this fits**
三段进度线是「完成一步、向前跳一格」的离散步骤，模式要求「略过目标再回弹、完成/当前/未完成三态清晰」。

**Interaction behavior**
- 触发：步骤卡滑到某一张，或地址/权限/连接状态变化。
- 开始：当前段填充从 0 直接补到 100%，前序段保持满格；节点从灰变青。
- 过程：每段延迟 70ms 依次绘制，形成「一段接一段」的节奏，而不是整条同时亮。
- 结束：填充到位后不回落；标签文字颜色与字重在 180ms 内切换，当前项加粗。
- 取消/失败：回退到前一步时，后序段清空（270ms 内），当前段保持 100%。
- 触控区：时间线本身不可点，只作状态展示（避免与卡片滑动抢手势）。
- 与技能要求的一致点：三态清晰、按步绘制；不一致点：没有「略过再回弹」的超调。

**Copyable prompt**
Create a spring stepper progress indicator for a three-step setup flow. When the current step advances, fill the newly completed segment to 100% with a 70 ms delay per segment so the line draws step by step, and recolor its node and label from muted gray to the accent color with a 180 ms transition; the active label becomes semibold. When stepping back, clear the later segments in about 270 ms while keeping the active segment full. The indicator is display-only: do not attach click handlers that would compete with the adjacent swipeable card. Keep the existing three labels and the n/3 counter, derive fill from data rather than animation state, and allow a small overshoot at the leading edge only when motion is enabled, falling back to a plain fill when reduced motion is on.

**落地差距**
- P2：给当前段末尾加 2–4px 的超调回弹（需用 JS 或额外元素，纯 CSS width 无法回弹）。

---

### 2.5 防截屏开关

**Selected interaction**
Ripple Feedback for Related Switches / 开关联动反馈。

**Why this fits**
这是「改一个开关，提醒它属于同一组设置」的场景；本 App 同组只有这一个开关，所以取模式中的「涟漪从开关扩散 + 状态立即翻转」部分，去掉邻居联动（没有邻居）。

**Interaction behavior**
- 触发：点抽屉底部的「防截屏保护」行或右侧开关。
- 开始：轨道颜色与圆点位置立即翻转；圆点带 260ms 轻微回弹（`cubic-bezier(0.34,1.56,0.64,1)`），同时 `switchSquash` 压到 0.86 再回 1（130ms）。
- 过程：文案从「截图与录屏显示为空白」变为「已关闭，界面可被截取」（橙色），仅关闭时变化。
- 结束：写入存储 `kira-shield` 并调用原生 `setSecure(boolean)`；重新打开 App 时按存储恢复。
- 取消/失败：关闭前弹确认框「关闭防截屏保护？」；取消则开关不动；原生调用失败时 toast「无法切换截屏保护，请重新打开 App」，开关回滚到原状态。
- 触控区：整行 64px 可点，开关本身 44×26 不单独缩小。
- 与技能要求的一致点：状态立即翻转、反馈不阻塞；已补开关中心涟漪（72px 圆环，300ms），且没有「相关开关」可联动。

**Copyable prompt**
Create a ripple-feedback interaction for a single privacy switch inside a settings drawer. When the user taps the row or the switch, change the underlying value first and animate the knob with a 260 ms spring that overshoots slightly, while the track color transitions at the same time; add a subtle press squash to the knob (0.86×, 130 ms). Expand a small circular ripple from the switch center to about twice the toggle width, fade it out, and do not let it intercept further taps. For destructive direction changes, ask for confirmation before applying the value; if the native call fails, revert the toggle and show an inline error. Update explanatory copy immediately when the state changes, keep the whole row a 64 px hit target, announce the new state to assistive technology, and remove the ripple and overshoot when reduced motion is enabled.

**落地差距**
- 已实现：开关中心向外扩一圈 72px 的淡青圆环，300ms 内放大并淡出。
- P2：`aria-checked` 已有，但缺少 `role="switch"` 的读屏状态播报验证。

---

### 2.6 「这台手机」叠卡

**Selected interaction**
Stacked Card Scroll / 卡片堆叠滚动。

**Why this fits**
三张信息卡以「前卡覆盖后卡、展开后能看到层层边缘」呈现，是卡片堆叠的形态；模式的核心是「滚动驱动时前卡被压扁、后卡按深度缩放」。

**Interaction behavior**
- 触发：点「这台手机」区域展开/收起。
- 开始：三张卡从 `top = i*9`、`scale = 1 - i*0.035` 的收拢态开始。
- 过程：展开时按 `i*70ms` 错峰把每张卡移到 `top = i*100`、`scale = 1`；收起时按 `(2-i)*50ms` 反向叠回。
- 结束：展开后三张卡都可读；收起后只露前卡与两层 9px/18px 边缘。
- 取消/失败：展开中再点一次，立即反向，不排队。
- 触控区：叠卡区域整块可点，高度 120px（收起）/300px（展开）。
- 与技能要求的一致点：层级、压缩、错峰都有；不一致点：由点击而非滚动驱动，后卡不随滚动逐渐显现。

**Copyable prompt**
Create a stacked-card interaction for three phone capability cards. Collapsed, stack them with a 9 px vertical offset per card and a 3.5% scale reduction so only the front card and two thin edges are visible. On tap, expand them to a 100 px offset per card at full scale with a 70 ms stagger in reading order; on the next tap, collapse them in reverse order with a 50 ms stagger. During either animation, keep each card's content laid out normally and do not let later cards clip the front card's text. Preserve the existing card content and the section header, keep the collapsed area a 120 px tap target, derive expanded state from a single boolean so a second tap always reverses immediately, and when reduced motion is enabled jump between the two states without stagger.

**落地差距**
- P2：如要严格贴合模式，可改为页面滚动驱动（滚动到该区时逐步展开），但会改变交互模型，需产品确认。

---

## 3. 不适用的三处（明确不硬套）

**连接成功反馈（收圆 + 勾 + 粒子）**
模式库面向布局/列表/滑杆/标签类交互，没有「单按钮成功微交互」这一项。强行归到 Staggered Bulk Selection 会误导实现（那是列表逐项勾选）。保留现有自定义反馈；只借用模式的通用要求：状态可逆（失败/停止能回到 idle）、动画不阻塞再次点击、减少动效时直接切终态。

**步骤详情面板（小卡扩张成全屏 + 下拉缩回）**
这是覆盖层接管，不是模式库里的「标签挤开」或「卡片删除」。保留现有实现；借用 Animated Text Disclosure 的原则：展开高度/位置由内容决定、可逆、拖拽中不抢页面滚动手势。

**侧边抽屉**
抽屉滑入不属于这 10 种；保留现有 320ms 滑入 + 60+i*36ms 条目错开。

---

## 4. 不采用的模式与原因

| 模式 | 不采用原因 |
|---|---|
| Radial Theme Transition / 圆形主题切换 | 本 App 没有明暗主题切换；页签切换曾用整页圆形扩散，观感是「整屏变白」，已改成局部涟漪。 |
| Drag-to-Reorder / 拖拽排序 | 没有可排序列表；步骤卡是线性流程，顺序不可改。 |
| Curved Card Deletion / 卡片曲线删除 | 没有可删除的卡片；步骤卡与信息卡都是只读。 |
| Animated Text Disclosure / 文本展开 | 关于页文案是常显，不需要折叠；详情面板用了覆盖层而非高度展开。 |
| Spring Stepper Progress | 时间线采用（见 2.4），但只取其「按步填充」，不取其超调。 |

---

## 5. 现状差距汇总

| 优先级 | 差距 | 影响 |
|---|---|---|
| P0 | 无 | 现有交互均可用，无阻塞 |
| P1 | 页签胶囊拉长时相邻页签不让位 | 拉伸会轻压两侧文字，与「挤压让位」不符 |
| 已修 | 偏好列表勾选错峰 | 加 `transitionDelay = index * 40ms`，批量修改依次落位 |
| 已修 | 防截屏开关涟漪 | 开关中心 72px 圆环，300ms 扩散淡出 |
| P2 | 时间线无超调 | 缺少「略过再回弹」的物理感 |
| P2 | 未接系统 `prefers-reduced-motion` | 只能在 App 内关动效，系统级无障碍设置无效 |
| P2 | 叠卡是点击驱动 | 与模式的滚动驱动形态不同（可接受） |

---

## 6. 落地顺序

1. **页签挤压让位**（改 `tab` 宽度/图标位移，风险低，观感提升明显）。
2. **偏好列表勾选错峰**（已实现，`transitionDelay = index * 40`）。
3. **防截屏开关涟漪**（已实现，`.shield-ripple` 72px 圆环）。
4. **时间线超调**（用 JS 逐帧或末尾 4px 元素，最后做）。
5. **reduced-motion 接入**（读系统设置，映射到 `effects` 三开关的只读降级）。

---

## 7. 验收断言

1. 点页签后，胶囊横向拉长可见（≥1.2×）并在 400ms 内回到 1×，页面没有缩放或白闪。
2. 卡片拖到 20% 宽度以下松手会回弹到原卡；超过阈值或速度 >0.5px/ms 才翻页。
3. 滚轮松手后 600ms 内停在某一刻度，越界拖动有阻尼且不越出首尾。
4. 取消一个偏好项后，环上点亮数量与中心数字在 500ms 内一致，总开关显示 `–`。
5. 关闭防截屏会先弹确认；取消后开关与 `kira-shield` 都不变；确认后 `setSecure(false)` 被调用。
6. 叠卡二次点击立即反向，展开/收起过程中不出现文字被裁切。
7. 关闭「涟漪反馈」或「卡片与连线」后，对应动效不再播放，功能仍可用。
