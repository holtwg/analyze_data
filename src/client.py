"""HTTP 客户端：统一处理 UA、Referer、编码与重试。

titan007 站点存在反爬，关键点是：
- 数据 JS 需要带 ``Referer`` 指向欧指列表页，否则可能返回空。
- ``odds_jc.txt`` 为 GBK，``*.js`` 为 UTF-8，需分别指定编码。
- 偶发连接抖动，做有限重试。
"""
from __future__ import annotations

import httpx

from .config import ODDS_LIST_PAGE, USER_AGENT

_DEFAULT_TIMEOUT = 30.0


def fetch_text(
    url: str,
    *,
    encoding: str = "utf-8",
    referer_match_id: str | None = None,
    referer: str | None = None,
) -> str:
    """抓取文本页面，自动处理编码与重试。

    Args:
        url: 目标 URL。
        encoding: 预期编码，``odds_jc.txt`` 用 ``gbk``，数据 JS 用 ``utf-8``。
        referer_match_id: 若提供，则设置 Referer 为对应欧指列表页（抓取数据 JS 时需要）。
        referer: 若提供，则直接用它作为 Referer（用于如 schedule.aspx 等自定义来源）。

    Returns:
        解码后的页面文本。

    Raises:
        httpx.HTTPStatusError: 非 2xx 且重试后仍失败。
    """
    headers = {"User-Agent": USER_AGENT}
    if referer is not None:
        headers["Referer"] = referer
    elif referer_match_id is not None:
        headers["Referer"] = ODDS_LIST_PAGE.format(match_id=referer_match_id)

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            resp = httpx.get(url, headers=headers, timeout=_DEFAULT_TIMEOUT, follow_redirects=True)
            resp.raise_for_status()
            resp.encoding = encoding
            return resp.text
        except (httpx.HTTPError, UnicodeDecodeError) as err:
            last_err = err
    raise RuntimeError(f"抓取失败 {url}: {last_err}") from last_err


def fetch_bytes(url: str, *, referer_match_id: str | None = None) -> bytes:
    """仅抓取字节（用于需要自行探测编码的场景）。"""
    headers = {"User-Agent": USER_AGENT}
    if referer_match_id is not None:
        headers["Referer"] = ODDS_LIST_PAGE.format(match_id=referer_match_id)
    resp = httpx.get(url, headers=headers, timeout=_DEFAULT_TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    return resp.content
