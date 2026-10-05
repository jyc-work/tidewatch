"""指标计算：多窗口收益 + 强弱四段（DESIGN §5.1 / §5.2）。

口径固定、可手算校验（对应 §10.1 验收项 #9）。
"""
from __future__ import annotations

ALGORITHM_VERSION = "momentum-v1"

STAGES = ("持续领涨", "高位回落", "超跌反弹", "持续走弱")


def returns_from_closes(
    closes: list[float], windows: tuple[int, ...] = (1, 5, 20)
) -> dict[int, float | None]:
    """closes 严格按时间升序，最后一个为当日。

    返回 {window: ret}；样本不足时该窗口为 None（不臆造 0）。
    """
    if not closes:
        return {w: None for w in windows}
    out: dict[int, float | None] = {}
    last = closes[-1]
    for w in windows:
        if len(closes) > w and closes[-1 - w]:
            out[w] = last / closes[-1 - w] - 1.0
        else:
            out[w] = None
    return out


def classify_stage(ret_20d: float | None, ret_1d: float | None) -> str | None:
    """强弱四段：20 日动量 × 当日动量 的正负四象限。

    | 20日 | 当日 | 标签     |
    |  +   |  +   | 持续领涨 |
    |  +   |  -   | 高位回落 |
    |  -   |  +   | 超跌反弹 |
    |  -   |  -   | 持续走弱 |
    """
    if ret_20d is None or ret_1d is None:
        return None
    if ret_20d >= 0 and ret_1d >= 0:
        return "持续领涨"
    if ret_20d >= 0 and ret_1d < 0:
        return "高位回落"
    if ret_20d < 0 and ret_1d >= 0:
        return "超跌反弹"
    return "持续走弱"
