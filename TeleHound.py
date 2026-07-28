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
RATE_LIMIT_PAUSE = 5
DEFAULT_DELAY = 0.34


def call(token: str, method: str, **params) -> dict:
    url = API.format(token=token, method=method)
    r = requests.post(
        url,
        json={k: v for k, v in params.items() if v is not None}
    )
    return r.json()


def copy_one(token: str, source: str, target: str, msg_id: int) -> dict:
    """Copy a single message from source to target."""
    return call(
        token,
        "copyMessage",
        chat_id=target,
        from_chat_id=source,
        message_id=msg_id
    )


def delete_one(token: str, source: str, msg_id: int) -> dict:

    """Delete a single message from source chat."""
    return call(
        token,
        "deleteMessage",
        chat_id=source,
        message_id=msg_id
    )


def get_webhook_info(token: str) -> dict:
    resp = call(token, "getWebhookInfo")

    if not resp.get("ok"):
        print(
            f"Webhook query failed: "
            f"{resp.get('description', 'unknown error')}"
        )
        return {}

    return resp["result"]


def print_webhook_info(webhook: dict):

    print()
    print("Webhook information")
    print("===================")

    print(
        f"URL: {webhook.get('url') or '(not configured)'}"
    )

    print(
        f"Pending updates: "
        f"{webhook.get('pending_update_count', 0)}"
    )

    if webhook.get("ip_address"):
        print(
            f"IP address: "
            f"{webhook.get('ip_address')}"
        )

    if webhook.get("has_custom_certificate"):
        print(
            "Custom certificate: enabled"
        )
    else:
        print(
            "Custom certificate: disabled"
        )

    if webhook.get("max_connections"):
        print(
            f"Max connections: "
            f"{webhook.get('max_connections')}"
        )

    if webhook.get("last_error_date"):
        print(
            f"Last error date: "
            f"{webhook.get('last_error_date')}"
        )

    if webhook.get("last_error_message"):
        print(
            f"Last error: "
            f"{webhook.get('last_error_message')}"
        )

    print()


def verify_bot(token: str) -> dict:
    resp = call(token, "getMe")

    if not resp.get("ok"):
        print(
            f"Bot auth failed: "
            f"{resp.get('description', 'unknown error')}"
        )
        sys.exit(1)

    return resp["result"]


def pull_range(token: str, source: str, target: str,
               msg_ids: list[int], delay: float,
               delete_after_copy: bool = False) -> list[dict]:

    results = []

    for i, mid in enumerate(msg_ids):

        resp = copy_one(
            token,
            source,
            target,
            mid
        )

        if resp.get("ok"):

            result = {
                "message_id": mid,
                "status": "ok",
                "data": resp["result"]
            }

            if delete_after_copy:

                delete_resp = delete_one(
                    token,
                    source,
                    mid
                )

                if delete_resp.get("ok"):

                    print(
                        f"  [{i+1}/{len(msg_ids)}] "
                        f"msg {mid} -> copied + deleted"
                    )

                    result["deleted"] = True

                else:

                    error = delete_resp.get(
                        "description",
                        "unknown"
                    )

                    print(
                        f"  [{i+1}/{len(msg_ids)}] "
                        f"msg {mid} -> copied "
                        f"(delete failed: {error})"
                    )

                    result["deleted"] = False
                    result["delete_error"] = error

            else:

                print(
                    f"  [{i+1}/{len(msg_ids)}] "
                    f"msg {mid} -> copied"
                )

            results.append(result)


        elif resp.get("error_code") == 429:

            wait = resp.get(
                "parameters",
                {}
            ).get(
                "retry_after",
                RATE_LIMIT_PAUSE
            )

            print(
                f"  [{i+1}/{len(msg_ids)}] "
                f"msg {mid} -> rate limited, "
                f"waiting {wait}s"
            )

            time.sleep(wait)

            resp = copy_one(
                token,
                source,
                target,
                mid
            )

            if resp.get("ok"):

                result = {
                    "message_id": mid,
                    "status": "ok",
                    "data": resp["result"]
                }

                if delete_after_copy:

                    delete_resp = delete_one(
                        token,
                        source,
                        mid
                    )

                    result["deleted"] = delete_resp.get("ok")

                results.append(result)

            else:

                desc = resp.get(
                    "description",
                    "unknown"
                )

                print(
                    f"  [{i+1}/{len(msg_ids)}] "
                    f"msg {mid} -> failed after retry: {desc}"
                )

                results.append(
                    {
                        "message_id": mid,
                        "status": "fail",
                        "error": desc
                    }
                )


        else:

            desc = resp.get(
                "description",
                "unknown"
            )

            print(
                f"  [{i+1}/{len(msg_ids)}] "
                f"msg {mid} -> skip ({desc})"
            )

            results.append(
                {
                    "message_id": mid,
                    "status": "skip",
                    "error": desc
                }
            )


        time.sleep(delay)


    return results



def main():

    p = argparse.ArgumentParser(
        description="Pull Telegram messages by sequential ID"
    )

    p.add_argument(
        "--token",
        required=True,
        help="Bot token secret (the part after the colon)"
    )

    p.add_argument(
        "--bot-id",
        required=True,
        help="Numeric bot user ID (the part before the colon)"
    )

    p.add_argument(
        "--source",
        required=True,
        help="Source chat ID"
    )

    p.add_argument(
        "--target",
        required=True,
        help="Target chat ID"
    )

    p.add_argument(
        "--start-id",
        required=True,
        type=int,
        help="Message ID to start from"
    )

    p.add_argument(
        "--forward",
        type=int,
        default=0,
        help="Optional: how many messages to pull forward"
    )

    p.add_argument(
        "--delete",
        action="store_true",
        help="Delete source messages after successful copy"
    )

    p.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help="Seconds between API calls"
    )

    p.add_argument(
        "--out",
        type=str,
        default="pull_results.json",
        help="Output JSON file"
    )


    args = p.parse_args()


    back_count = args.start_id

    full_token = f"{args.bot_id}:{args.token}"


    bot = verify_bot(full_token)


    print(
        f"Bot: @{bot['username']} (id {bot['id']})"
    )
    
    webhook = get_webhook_info(full_token)

    print_webhook_info(webhook)
    
    print(
        f"Source chat: {args.source}"
    )

    print(
        f"Target chat: {args.target}"
    )

    print(
        f"Start ID: {args.start_id}  |  "
        f"back: {back_count}  |  "
        f"forward: {args.forward}"
    )

    if args.delete:
        print("Delete mode: ENABLED")

    print()


    all_results = []


    # Backward
    if back_count > 0:

        ids = list(
            range(
                args.start_id,
                args.start_id - back_count,
                -1
            )
        )

        print(
            f"Pulling {len(ids)} messages backward "
            f"({ids[0]} -> {ids[-1]}):"
        )

        all_results.extend(
            pull_range(
                full_token,
                args.source,
                args.target,
                ids,
                args.delay,
                args.delete
            )
        )

        print()


    # Forward
    if args.forward > 0:

        ids = list(
            range(
                args.start_id + 1,
                args.start_id + args.forward + 1
            )
        )

        print(
            f"Pulling {len(ids)} messages forward "
            f"({ids[0]} -> {ids[-1]}):"
        )

        all_results.extend(
            pull_range(
                full_token,
                args.source,
                args.target,
                ids,
                args.delay,
                args.delete
            )
        )

        print()


    ok = sum(
        1 for r in all_results
        if r["status"] == "ok"
    )

    skip = sum(
        1 for r in all_results
        if r["status"] == "skip"
    )

    fail = sum(
        1 for r in all_results
        if r["status"] == "fail"
    )


    total = len(all_results)


    print(
        f"Done: {ok} copied, "
        f"{skip} skipped, "
        f"{fail} failed "
        f"(total {total})"
    )


    Path(args.out).write_text(
        json.dumps(
            all_results,
            indent=2,
            default=str
        )
    )


    print(
        f"Results saved to {args.out}"
    )



if __name__ == "__main__":
    main()
