# 菜单与底栏角色表情

共九张透明 PNG，均以用户提供的蓝发角色图为参考，由内置 imagegen 生成。

| 文件 | 表情和动作 | 用途 |
| --- | --- | --- |
| hello.png | 微笑挥手 | 迎接 |
| connected.png | 开心眨眼比赞 | 连接成功 |
| call.png | 戴耳麦、侧耳说话，另一手摊开 | 通话菜单、通话底栏与正在通话 |
| device.png | 一手持手机，另一手点击屏幕 | 设备菜单、设备底栏与权限就绪 |
| link.png | 双手把连接线接口对齐接上 | 连接菜单、连接底栏与正在接通 |
| guide.png | 一手托开书，另一手指向说明页 | 使用说明与等待思考 |
| about.png | 手持齿轮，另一手转动调整 | 关于菜单与动效开启 |
| rest.png | 闭眼依靠袖子休息 | 停止、关闭、静音 |
| shield.png | 认真护住盾牌 | 防截屏保护开启 |

五个菜单按钮使用角色图替换蓝点。下方六个只读状态格分别显示手机连接、App 通话、无障碍、防截屏、界面动效与麦克风实验；表情和文字根据原生确认的当前状态切换。连接中和接通中不算已连接；静音仍保留通话状态，只切换为安静表情。状态格本身不会启动功能。

底栏常驻设备、连接和通话三张图片；菜单其余图片在抽屉打开时挂载。图片不随选中状态换源，没有自动轮播或呼吸定时器。当前五张按钮动作的完整生成提示词见 `button-prompts.json`；早期六张的生成记录见 `prompts.json`，其中同名按钮图已由本次重绘替换。输入参考为原始角色图和首批 Q 版画风。

## 首批表情的生成记录

生成提示词的共同部分：

> Use case: stylized-concept. Asset: ONE small transparent chibi reaction sticker for an Android app's side drawer. Use the attached image only as character/color reference: periwinkle blue hair with a long side-swept fringe, large bright cyan-blue eyes, soft pale skin, cozy white and pale-blue scarf/hoodie. Cute super-deformed anime bust, large head and little hands, clean expressive linework, icy blue and lavender palette, subtle white sticker outline, legible at 96 px. Center the entire character with comfortable transparent padding, isolated on genuinely transparent alpha. No panels, no background, no words, no watermark, no grid.

各图分别追加：

1. Expression: warm greeting, happy open eyes and little smile, right hand waving hello.
2. Expression: pleased connection-success reaction, smiling wink, one hand giving a clear thumbs-up and one tiny cyan sparkle.
3. 最初的 call.png 为戴耳机倾听动作，现已换为 `button-prompts.json` 中更明确的通话动作。
