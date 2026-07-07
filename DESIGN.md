# Design

校声智枢（Campus AI Agent）视觉系统。所有令牌定义在 `frontend/src/assets/style.css`，
Element Plus 主题通过 `--el-*` 变量整体覆盖，页面不允许硬编码颜色。

## Theme

沉稳、可信、精密。深靛蓝品牌色 + 冷调藏青灰中性色，全浅色基调；
品牌感来自精密的层次、留白与一致性，而非装饰。参照 Linear / 语雀的克制精致。

## Colors

- **Primary（品牌靛蓝）**: `#3b5bdb`（`--brand-600`，oklch ≈ 0.50 0.17 268）。
  完整色阶 `--brand-50 … --brand-900`。hover `--brand-500`，active/深文字 `--brand-700`，
  浅底选中态 `--brand-50`，边框强调 `--brand-200/300`。
- **中性色（冷调藏青灰）**: 页面底 `#f4f6fa`，表面 `#fff`，次级表面 `#f8fafd`，
  边框 `#e2e7f0` / `#ecf0f6`；文字四级：`#1c2434` / `#4d5a72` / `#6b788f` / `#8a95ab`。
- **语义色（降饱和）**: danger `#d23f45`（文字 `#b02a30`，底 `#fdeeef`，边 `#f4c2c4`）；
  warning `#b97708`（文字 `#96600a`，底 `#fdf5e6`，边 `#ecd9ae`）；
  success `#34924b`（文字 `#2a7540`，底 `#eef8f0`，边 `#c8e5d0`）。
  语义色只用于状态，不做装饰。
- **平台身份色**（帖子来源 pill，全站统一）: 微博 `#c2410c/#fff7ed`，
  小红书 `#be123c/#fff1f2`，贴吧 `#1d4ed8/#eff6ff`。
- 阴影带藏青色调（`rgba(23,32,63,…)`），两级：`--shadow-xs`、`--shadow-card`，浮层 `--shadow-raised`。

## Typography

- 系统栈：`system-ui, 'Segoe UI', 'PingFang SC', 'HarmonyOS Sans SC', 'MiSans', 'Microsoft YaHei'`，
  不引入外部字体。
- 全局 `font-variant-numeric: tabular-nums`（数据平台，数字必须等宽对齐）。
- 层级靠字重（600/700）与字号，不靠颜色；大标题 letter-spacing `-0.01em`。
- 数值/KPI 一律墨色 `--color-text`，语义色由图标块承载（见 StatCard）。

## Components

- **BrandLogo.vue**: 声波汇聚枢纽 SVG 标志；favicon 为 `public/brand.svg`。
- **StatCard.vue**: 图标块（36px 圆角、语义色浅底）+ 墨色数值 + muted 描述；
  支持 `loading`（shimmer 骨架）；icon 接受 EP 组件（全站禁用 emoji 图标）。
- **状态标签**: `.badge-high/mid/low`（风险）与 `.admin-page .status-*`（流程状态），
  一律"浅底 + 深文字"，禁纯色实心大面积。
- **表格**: th 底 `--color-surface-2`，行 hover `--color-surface-2`，
  选中行 `--brand-50`（禁止左侧色条指示）。
- **空态**: 图标 + 主句 + 补充说明 + 可选动作按钮；"平稳/无风险"类空态用 success 图标传达安心。
- **加载**: 列表用骨架屏（shimmer），Agent 长等待（20~180s）用阶段文案 + 计时 + 流动进度条。

## Motion

- 令牌：`--dur-fast` 150ms / `--dur` 200ms / `--dur-slow` 250ms，曲线 `--ease-out`
  （cubic-bezier(0.22,1,0.36,1)）。
- 只传达状态：hover 色变/微抬升、按压 `scale(0.97~0.985)`、路由过渡淡入+6px 上移。
- 入场动效：CSS `backwards` 填充 + 只写 from 帧（结束后回归自然样式，不锁死 hover）；
  KPI 数字滚动内置于 StatCard（rAF）；趋势线 `pathLength` draw-on。
- **GSAP（3.15，本地 npm）只用于两类 CSS 做不到的场景**：登录页 master timeline 编排、
  事件列表 Flip 位移动画。模式：`gsap.context()` 作用域 + 卸载 `revert()/kill()`；
  禁止用于装饰性循环动画和 ScrollTrigger 滚动叙事。skill 参考 `.claude/skills/gsap-*`。
- 全局 `prefers-reduced-motion: reduce` 降级（style.css 处理 CSS 动效；
  JS 驱动的动效必须自查 `matchMedia`）。

## Layout

- 侧栏 236px（收起 68px，localStorage 记忆）；≤1024px 自动收起，≤768px 抽屉 + 遮罩。
- 圆角三档：6 / 10 / 14（`--radius-sm/--radius/--radius-lg`）。
- 层次优先用留白、表面色差与字重，少用边框；禁嵌套卡片。
- z-index 刻度：`--z-topbar 80`、`--z-sidebar 100`、`--z-overlay 900`。

## 禁则（本项目已清除，勿再引入）

Ant 默认蓝 #1890ff、emoji/字符当图标、左侧色条强调、gradient text、
玻璃拟态、彩色 KPI 数字、纯黑阴影、暖冷灰混用。
