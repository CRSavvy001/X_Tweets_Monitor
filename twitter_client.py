"""Minimal async client for twitterapi.io.

Docs: https://docs.twitterapi.io/api-reference/endpoint/get_user_last_tweets
"""

import asyncio
import httpx

BASE_URL = "https://api.twitterapi.io"


class TwitterAPIError(Exception):
    pass


class TwitterAPIClient:
    def __init__(self, api_key: str, timeout: float = 15.0):
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"X-API-Key": api_key},
            timeout=timeout,
            # Don't keep idle connections open — some network layers (e.g.
            # Railway's proxy) silently drop them, which surfaces as a
            # confusing httpcore/httpx traceback on the next reuse.
            limits=httpx.Limits(max_keepalive_connections=0, keepalive_expiry=0),
        )

    async def get_last_tweets(self, username: str, retries: int = 2) -> list[dict]:
        """Return the user's tweets, newest first. Retries on transient network errors."""
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                resp = await self._client.get(
                    "/twitter/user/last_tweets", params={"userName": username}
                )
            except httpx.HTTPError as e:
                last_err = e
                if attempt < retries:
                    await asyncio.sleep(1.5)
                    continue
                raise TwitterAPIError(f"network error after {retries} retries: {e!r}") from e

            if resp.status_code != 200:
                raise TwitterAPIError(f"HTTP {resp.status_code}: {resp.text[:200]}")

            data = resp.json()

            if isinstance(data, dict) and data.get("status") == "error":
                raise TwitterAPIError(data.get("message", "unknown error"))

            tweets = None
            if isinstance(data, dict):
                tweets = data.get("tweets")
                if tweets is None and isinstance(data.get("data"), dict):
                    tweets = data["data"].get("tweets")
            return tweets or []

        raise TwitterAPIError(f"network error: {last_err!r}")

    async def aclose(self):
        await self._client.aclose()
