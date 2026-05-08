#!/usr/bin/env python3
"""
Pull messages from a Telegram source chat and copy them into a target chat.

Telegram message IDs are sequential integers within each chat. Given a
starting message ID, this script walks backward N messages and forward M
messages, using the Bot API's copyMessage endpoint to reproduce each
message in the target chat (text, photos, stickers, documents, etc.).

Requirements: pip install requests
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

API = "https://api.telegram.org/bot{token}/{method}"
RATE_LIMIT_PAUSE = 5  # seconds to wait on 429
DEFAULT_DELAY = 0.34  # ~3 req/s, under Telegram's 30 req/s bot limit


def call(token: str, method: str, **params) -> dict:
    url = API.format(token=token, method=method)
    r = requests.post(url, json={k: v for k, v in params.items() if v is not None})
    return r.json()


def copy_one(token: str, source: str, target: str, msg_id: int) -> dict:
    """Copy a single message from source to target. Returns the API response."""
    return call(token, "copyMessage",
                chat_id=target, from_chat_id=source, message_id=msg_id)


def verify_bot(token: str) -> dict:
    resp = call(token, "getMe")
    if not resp.get("ok"):
        print(f"Bot auth failed: {resp.get('description', 'unknown error')}")
        sys.exit(1)
    return resp["result"]


def pull_range(token: str, source: str, target: str,
               msg_ids: list[int], delay: float) -> list[dict]:
    results = []
    for i, mid in enumerate(msg_ids):
        resp = copy_one(token, source, target, mid)

        if resp.get("ok"):
            print(f"  [{i+1}/{len(msg_ids)}] msg {mid} -> copied")
            results.append({"message_id": mid, "status": "ok", "data": resp["result"]})
        elif resp.get("error_code") == 429:
            wait = resp.get("parameters", {}).get("retry_after", RATE_LIMIT_PAUSE)
            print(f"  [{i+1}/{len(msg_ids)}] msg {mid} -> rate limited, waiting {wait}s")
            time.sleep(wait)
            resp = copy_one(token, source, target, mid)
            if resp.get("ok"):
                print(f"  [{i+1}/{len(msg_ids)}] msg {mid} -> copied (retry)")
                results.append({"message_id": mid, "status": "ok", "data": resp["result"]})
            else:
                desc = resp.get("description", "unknown")
                print(f"  [{i+1}/{len(msg_ids)}] msg {mid} -> failed after retry: {desc}")
                results.append({"message_id": mid, "status": "fail", "error": desc})
        else:
            desc = resp.get("description", "unknown")
            print(f"  [{i+1}/{len(msg_ids)}] msg {mid} -> skip ({desc})")
            results.append({"message_id": mid, "status": "skip", "error": desc})

        time.sleep(delay)

    return results


def main():
    p = argparse.ArgumentParser(description="Pull Telegram messages by sequential ID")
    p.add_argument("--token",     required=True, help="Bot token secret (the part after the colon)")
    p.add_argument("--bot-id",    required=True, help="Numeric bot user ID (the part before the colon)")
    p.add_argument("--source",    required=True, help="Source chat ID (messages pulled from here)")
    p.add_argument("--target",    required=True, help="Target chat ID (messages copied to here)")
    p.add_argument("--start-id",  required=True, type=int, help="Message ID to start from (also used as backward count)")
    p.add_argument("--forward",   type=int, default=0, help="Optional: how many messages to pull forward (newer)")
    p.add_argument("--delay",     type=float, default=DEFAULT_DELAY, help="Seconds between API calls")
    p.add_argument("--out",       type=str, default="pull_results.json", help="Output JSON file")
    args = p.parse_args()

    back_count = args.start_id

    full_token = f"{args.bot_id}:{args.token}"

    bot = verify_bot(full_token)
    print(f"Bot: @{bot['username']} (id {bot['id']})")
    print(f"Source chat: {args.source}")
    print(f"Target chat: {args.target}")
    print(f"Start ID: {args.start_id}  |  back: {back_count}  |  forward: {args.forward}")
    print()

    all_results = []

    # Backward: start_id, start_id-1, ..., 1
    if back_count > 0:
        ids = list(range(args.start_id, args.start_id - back_count, -1))
        print(f"Pulling {len(ids)} messages backward ({ids[0]} -> {ids[-1]}):")
        all_results.extend(pull_range(full_token, args.source, args.target, ids, args.delay))
        print()

    # Forward: start_id+1, start_id+2, ..., start_id+forward
    if args.forward > 0:
        ids = list(range(args.start_id + 1, args.start_id + args.forward + 1))
        print(f"Pulling {len(ids)} messages forward ({ids[0]} -> {ids[-1]}):")
        all_results.extend(pull_range(full_token, args.source, args.target, ids, args.delay))
        print()

    ok    = sum(1 for r in all_results if r["status"] == "ok")
    skip  = sum(1 for r in all_results if r["status"] == "skip")
    fail  = sum(1 for r in all_results if r["status"] == "fail")
    total = len(all_results)

    print(f"Done: {ok} copied, {skip} skipped, {fail} failed  (total {total})")

    Path(args.out).write_text(json.dumps(all_results, indent=2, default=str))
    print(f"Results saved to {args.out}")


if __name__ == "__main__":
    main()
