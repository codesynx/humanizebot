import asyncio
import logging

import aiohttp

from config import HUMANIZER_API_URL, HUMANIZER_EMAIL, HUMANIZER_PASSWORD

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
RETRY_DELAY = 5


async def humanize_text(text: str) -> str:
    """Send text to ai-text-humanizer.com API and return humanized result."""
    payload = {
        "email": HUMANIZER_EMAIL,
        "pw": HUMANIZER_PASSWORD,
        "text": text,
    }

    word_count = len(text.split())
    logger.info("API request: sending %d words (%d chars) to %s", word_count, len(text), HUMANIZER_API_URL)

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            logger.info("API attempt %d/%d starting...", attempt + 1, MAX_RETRIES + 1)
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    HUMANIZER_API_URL,
                    data=payload,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    body = await resp.text()

                    logger.info(
                        "API response: status=%d, body_length=%d, preview=%s",
                        resp.status, len(body), repr(body[:150]),
                    )

                    if resp.status == 200 and body.strip():
                        result = body.strip()
                        logger.info("API success: received %d chars (%d words)", len(result), len(result.split()))
                        return result

                    if resp.status == 429:
                        logger.error("API rate limit exceeded (429)")
                        raise HumanizerAPIError("Rate limit exceeded (429)")

                    if resp.status >= 500:
                        last_error = f"Server error {resp.status}: {body[:200]}"
                        logger.warning("API attempt %d/%d failed: %s", attempt + 1, MAX_RETRIES + 1, last_error)
                        if attempt < MAX_RETRIES:
                            await asyncio.sleep(RETRY_DELAY)
                            continue
                        raise HumanizerAPIError(last_error)

                    last_error = f"Unexpected response ({resp.status}): {body[:200]}"
                    logger.error("API unexpected response: %s", last_error)
                    raise HumanizerAPIError(last_error)

        except aiohttp.ClientError as e:
            last_error = str(e)
            logger.warning("API network error attempt %d: %s", attempt + 1, last_error)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
                continue
            raise HumanizerAPIError(f"Network error: {last_error}")

    raise HumanizerAPIError(last_error or "Unknown error")


class HumanizerAPIError(Exception):
    pass
