# 花屏模拟器 GlitchSim —— 屏线故障悬浮层

一个**完全透明的悬浮层**：只在屏幕上画"屏线（LVDS/eDP 排线）接触不良"的彩色竖条纹，
你真正的桌面原样透在下面，鼠标键盘照常能用。按 **ESC** 立刻恢复。

> 对应 PRD：`..\花屏模拟器-PRD.md`

## 运行

双击 `运行.bat`，或直接跑 `dist\花屏模拟器.exe`。

## 它长什么样

- 竖线**位置固定**（坏的就是那几根），纯色、全高贯穿、边缘锐利，宽度 1~2 物理像素；
- **成簇**出现——排线里某一段接触不良，往往是一片同色的密集细线；
- 再撒几根孤立细线、偶尔一条宽色带；
- 故障区可能带一片**半透明的发白/发绿**（接触不良的泛色）；
- 极偶尔整屏闪一下。**没有噪点、没有马赛克**——那是"显卡花屏"，不是"屏线坏"。

## 用法

| 操作 | 作用 |
|------|------|
| **退出键**（默认 `ESC` / `Ctrl+Alt+Q`） | 退出并恢复 |
| `+` / `-` | 加 / 减竖线密度 |
| 托盘图标右键 | 暂停继续 / 退出 |

窗口带 `WS_EX_TRANSPARENT`，鼠标点击直接穿透到下面的真实桌面——
所以"屏线坏了"的时候你还能继续操作电脑，这才是最真的地方。

### 自定义退出键

改 `config.ini` 的 `exit_keys`（或 `--exit-keys "f8"`），多个用逗号分隔，
支持 `ctrl` / `alt` / `shift` / `win` 修饰键：

```ini
exit_keys = esc, ctrl+alt+q      ; 默认
exit_keys = f8                   ; 只用 F8
exit_keys = ctrl+shift+k         ; 组合键
exit_keys = win+x, delete        ; 多个
```

可用键名：`esc` `space` `enter` `tab` `backspace` `insert` `delete` `home` `end`
`pageup` `pagedown` `printscreen` `scrolllock` `pause`、方向键 `left/up/right/down`、
字母 `a`~`z`、数字 `0`~`9`、功能键 `f1`~`f24`，以及 `-` `=` `[` `]` `;` `'` `,` `.` `/` `\` `` ` ``。

> **`Ctrl+Alt+Q` 是硬编码的终极兜底，永远有效**（即使你把 `esc` 从配置里删掉），
> 防止配错键把自己锁死。

### 开机启动

直接在 `config.ini` 里改就行，**改完下次运行自动生效**：

```ini
autostart = true      ; 开
autostart = false     ; 关
```

程序每次启动都会把 ini 里的值同步到系统（多了就建、少了就删，状态一致则不动）。
实现方式是往用户「启动」文件夹
（`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`）放一个 VBS 启动器，
**不动注册表**，不想用了把 `autostart` 改回 `false` 或直接删掉那个文件即可。

命令行也可以（`--autostart on` 会顺带把 config.ini 一起改了，保持两边一致）：

```bat
花屏模拟器.exe --autostart on
花屏模拟器.exe --autostart off
```

> 建议开机自启时把 `delay` 设成 30~60（进桌面后过一会儿再花），
> 或者设 `duration` 让它自己恢复，免得回来还得手动按退出键。

## 配置

改 `config.ini`，或用命令行（优先级更高）：

```bat
main.py --intensity 0.9          :: 更密更惨
main.py --duration 10            :: 10 秒后自动恢复
main.py --delay 30               :: 启动 30 秒后才出现
main.py --exit-keys "ctrl+shift+k"
main.py --autostart on / off     :: 开机启动
main.py --no-hint                :: 不弹托盘提示（整蛊用）
main.py --fps 30                 :: 更省 CPU
main.py --preview preview        :: 导出效果图 PNG（不建窗口）
main.py --selftest               :: 自检 + 性能基准
```

## 打包

```bat
打包exe.bat
```

产物 `dist\花屏模拟器.exe`，单文件免安装，只带 numpy。

## 安全与隐私

- **不截屏、不写盘、不联网、不写注册表**。竖线是画在一个透明层上的，
  底下的桌面照常显示，程序根本拿不到你的画面。
- `ESC` / `Ctrl+Alt+Q` 走系统级低级键盘钩子，即使窗口不可见也**始终生效**，从不吞按键。
- 杀进程 / 崩溃：只影响本进程，无任何系统状态残留。
- 托盘图标是保底退出入口。
