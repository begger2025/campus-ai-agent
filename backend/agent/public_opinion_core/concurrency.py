"""并发地跑注入进来的 per-event / per-cluster LLM 调用——**而结果必须逐位不变**。

**被修的缺陷**（实测）：`scripts/generate_public_events.py` 每跑一次要打 90+ 次**串行** LLM
调用（37 个事件 × 2 + N 个簇），单次 4~7 秒，合计 7~8 分钟。而这些调用**互不依赖**：
判「宿舍火灾有多严重」不需要先知道「食堂涨价」判成了什么。串行在这里不是必要，是浪费。

**这个模块存在的理由，是"并行之后结果不许变"比"并行"本身难得多。**

线程池最自然的写法是按完成顺序收结果：

    for future in as_completed(futures):    # 谁先回来谁先进列表
        results.append(future.result())

它是**错的**，而且错得很隐蔽：网络快的事件排到前面，于是同一批输入每跑一次得到一个不同的
顺序——第 3 个事件的风险研判被安到第 7 个事件头上。这些研判要落库、要排看板、要喂消融
实验（`scripts/ablation_event_*.py`），而消融的全部意义就是"任何人重跑都得到同一份结果"。
所以本模块的契约是：

    **输出列表与输入列表等长、同序、一一对应，与完成顺序无关。**

实现上靠 `executor.map`（它按**提交顺序**产出结果，不是完成顺序）。

**异常就地捕获，不往外抛**（`Outcome.error`）。这是既有的"逐事件降级"语义的前提：一个事件
的 LLM 挂了，别的事件照常出结果。如果让异常从 `executor.map` 的迭代里抛出来，它会**中断
整轮迭代**——一个超时就会带走后面所有还没取回的事件，把"逐事件降级"悄悄变成"整批丢失"。

**并发度 1 = 真串行**：不开线程池，调用就发生在调用者的线程里。这不只是省一点开销——
它让"并发度 1"成为一个**可断言的、逐位等价于改造前**的对照臂（消融要用它当基线）。

本模块只用标准库（`concurrent.futures` 是 stdlib）：核心包对 HTTP、模型名、API key 一无所知，
这条边界一个字节都不许破（同 llm_risk / llm_lifecycle / llm_refine 的依赖注入口径）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Generic, TypeVar


# 默认并发度。8 的来由：
#   - 单次调用 4~7s，几乎全是**等网络**（GIL 在等 I/O 时是放开的，所以线程池在这里是对的
#     工具，不需要进程池）；37 个事件 ÷ 8 ≈ 5 轮 × 5s ≈ 25s，够把 7~8 分钟压到 1 分钟出头；
#   - 再往上加收益递减，而代价是实打实的：LLM 服务商按并发限流（429 会触发 call_llm 的重试
#     退避，反而更慢），本机与端点之间的连接数也不是免费的（httpx 连接池按 8 的一倍余量配的，
#     见 llm_client._get_http_client）；
#   - 部署侧可经 .env `EVENT_LLM_CONCURRENCY` 覆盖（限流严的端点调小，1 = 退回串行）。
DEFAULT_LLM_CONCURRENCY = 8

T = TypeVar("T")
R = TypeVar("R")


@dataclass(slots=True)
class Outcome(Generic[R]):
    """一次调用的结局：要么有值，要么有异常。**两者都不许把别的调用带下水。**

    调用方按 `error is not None` 判断降级（而不是靠 value 是不是 None——`None` 本身
    是 assessor 的合法返回值，意思是"这次研判不可用"，和"调用炸了"是两种不同的失败，
    warning 的措辞也不同）。
    """

    value: R | None = None
    error: BaseException | None = None


def resolve_concurrency(value: int | None) -> int:
    """把外部传进来的并发度收成一个 >= 1 的整数。

    None = 用默认值（8）。0 / 负数 = 串行（1），**不是"不调用"**：一个把并发度配成 0 的
    .env 绝不能让整条流水线的 LLM 研判静默消失。
    """

    if value is None:
        return DEFAULT_LLM_CONCURRENCY
    return max(int(value), 1)


def map_calls(
    call: Callable[[T], R],
    items: Sequence[T],
    *,
    concurrency: int | None = DEFAULT_LLM_CONCURRENCY,
    thread_name_prefix: str = "llm",
) -> list[Outcome[R]]:
    """并发地对每个 item 跑一次 call；返回**与输入等长、同序**的结局列表。

    - 顺序：`executor.map` 按提交顺序产出，与谁先返回无关（这是本模块的全部意义）；
    - 异常：在 worker 里就地捕获成 `Outcome.error`，绝不让它中断整轮迭代；
    - 并发度 <= 1：不开线程池，就地串行跑（逐位等价于改造前的 for 循环）。
    """

    if not items:
        return []

    workers = min(resolve_concurrency(concurrency), len(items))
    if workers <= 1:
        return [_run(call, item) for item in items]

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=thread_name_prefix) as executor:
        # map 而不是 as_completed：前者按**提交顺序**产出结果，后者按完成顺序——
        # 而完成顺序取决于网络，是这次并行化唯一能毁掉可复现性的地方。
        # （把这一行换成 as_completed + append，本文件的 12 个用例会立刻变红。）
        return list(executor.map(lambda item: _run(call, item), items))


def _run(call: Callable[[T], R], item: T) -> Outcome[R]:
    try:
        return Outcome(value=call(item))
    except Exception as exc:  # 超时、网络、SDK 里任何东西——和串行版的 try 边界一模一样
        return Outcome(error=exc)


__all__ = [
    "DEFAULT_LLM_CONCURRENCY",
    "Outcome",
    "map_calls",
    "resolve_concurrency",
]
