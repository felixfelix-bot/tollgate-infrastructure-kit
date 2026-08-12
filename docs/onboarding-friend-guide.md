# Friend Onboarding Guide

This guide walks you through everything you need to start using your personal AI assistant hosted on the Tollgate infrastructure. You will learn how to install the Buzz chat client, connect to the relay, authenticate with your Nostr identity, talk to your Hermes AI agent, manage kanban tasks, dispatch workers, understand quality gates, use Cashu credits, and set up a NIP-05 identity.

No prior knowledge of Nostr, Bitcoin, or AI tooling is required. Each section builds on the previous one. Follow them in order the first time; afterwards you can skip to whichever section you need as a reference.

---

## 1. Installing Buzz

Buzz is a desktop and mobile Nostr client that supports NIP-29 group chat. It is the front-end you use to interact with your Hermes agent — think of it as your chat window into the system.

### Desktop (recommended)

1. Go to the Buzz releases page: https://github.com/obelisk-app/buzz/releases
2. Download the build for your operating system:
   - **macOS**: `.dmg` file (Apple Silicon or Intel depending on your Mac)
   - **Windows**: `.exe` installer
   - **Linux**: `.AppImage` or `.deb` package
3. Install and launch Buzz.
4. On first launch Buzz will create a new Nostr identity for you automatically. You will see your npub (a long string starting with `npub1...`) displayed in the settings or profile section.

### Web client (fallback)

If you cannot install the desktop app, a web version is available at:

```
https://chat.<your-domain>
```

Replace `<your-domain>` with the domain your operator gave you (for example, `orangesync.tech`). The web client works in Chrome, Firefox, and Safari. Your identity is stored in the browser, so use the same browser every time.

### Importing an existing key (optional)

If you already have a Nostr key (for example from Damus, Amethyst, or another client):

1. Open Buzz settings.
2. Find the **Private Key** or **Import Key** section.
3. Paste your `nsec1...` secret key.
4. Buzz will switch to your existing identity.

If you do not have a key, skip this step — Buzz creates one for you.

### Locking your identity

Buzz lets you encrypt your private key with a password. This is strongly recommended on shared computers. If you set a password, you will need it every time you launch Buzz. Lose it and you lose access to your identity — there is no password reset. Write it down somewhere safe.

### Sharing your npub

Once Buzz is set up, copy your npub (`npub1...`) and send it to your operator (the person who invited you). They need it to whitelist you on the relay and assign you a Hermes bot. Until they do, you will not be able to connect or see any groups.

---

## 2. Connecting to the Relay

The relay is the server that routes messages between you and your Hermes agent. It uses the Nostr protocol over WebSocket. Your operator has deployed a relay at a specific URL.

### Relay URL

Ask your operator for the relay URL. It looks like:

```
wss://relay.<your-domain>
```

For example: `wss://relay.orangesync.tech`

### Adding the relay in Buzz

1. Open Buzz settings.
2. Navigate to the **Relays** section.
3. Click **Add Relay** (or the `+` button).
4. Paste the relay URL: `wss://relay.<your-domain>`
5. Enable both **Read** and **Write** for this relay.
6. Save.

Buzz will attempt to connect immediately. You should see a green or connected indicator next to the relay. If it stays red or says "disconnected":

- Check that the URL is correct (no trailing slash, starts with `wss://`)
- Verify your internet connection
- Ask the operator to confirm the relay is running

### Why only this relay

Your operator runs a private relay with NIP-42 authentication. Public relays like `wss://relay.damus.io` will not have your groups or your Hermes bot. Always connect to your operator's relay. You can connect to public relays for general Nostr use, but your Hermes interaction happens exclusively on the private relay.

---

## 3. NIP-42 Authentication

NIP-42 is the Nostr authentication protocol that lets the relay verify you are who you claim to be. The relay challenges you to sign a cryptographic proof with your private key. This prevents impersonation and keeps the relay private.

### How it works (the short version)

1. You connect to the relay (done in the previous section).
2. The relay sends an `AUTH` challenge containing a random string.
3. Buzz automatically signs this challenge with your private key (`nsec`).
4. The relay verifies the signature against your public key (`npub`).
5. If your npub is on the whitelist, you are granted access.

This happens automatically in Buzz — you do not need to do anything manually. If authentication succeeds, you will see your groups and channels appear. If it fails, you will see an error or an empty screen.

### If authentication fails

1. **Wrong npub**: Make sure you sent the correct npub to your operator. Compare the npub displayed in Buzz settings with the one your operator has on file.
2. **Not whitelisted**: Ask your operator to add your npub to the relay's whitelist. The relay rejects all unrecognised keys.
3. **Key mismatch**: If you imported a key, verify the nsec is correct. A typo in the nsec means the npub will not match what the operator whitelisted.
4. **Relay restarted**: If the relay was just restarted, wait 10 seconds and Buzz will reconnect and re-authenticate automatically.

### Security note

Your private key (`nsec`) never leaves your device. Buzz signs the challenge locally and sends only the signature. The relay never sees your private key. Keep your nsec private — anyone with your nsec can impersonate you on Nostr.

---

## 4. Joining Your Group

Once authenticated, you need to join the NIP-29 group that was created for you. A group is a channel where you and your Hermes bot exchange messages. Think of it as a private chat room.

### Finding your group

When your operator deployed your Hermes instance, they created a NIP-29 group and added your npub as a member. In Buzz:

1. Look for the **Groups** or **Channels** sidebar.
2. You should see a group named after you (for example, "Alice's AI" or "friend-1").
3. Click on it to open the chat.

If you do not see any groups:

- Confirm with your operator that your npub was added to the group.
- Try refreshing Buzz (close and reopen).
- Check that you are connected to the correct relay (Section 2).

### Group structure

Each group has:

- **You** — the human member, sending messages from Buzz.
- **Your Hermes bot** — an AI agent with its own Nostr identity, responding to your messages.
- **The operator** (optional) — your operator may be in the group for support and monitoring.

Messages sent to the group are visible to all members. Your Hermes bot reads every message addressed to it and responds in the same group.

### Mentioning the bot

To get the bot's attention, mention it by npub or use its name. Your operator will tell you the bot's name or npub. In Buzz, you can type:

```
@botname hello, can you help me with a task?
```

or paste the bot's npub directly. The bot will respond in the same channel.

---

## 5. Messaging Hermes

Hermes is your AI assistant. You talk to it through the Buzz group chat, just like messaging a person. Hermes can answer questions, write code, research topics, manage tasks, and run automated workflows.

### Sending your first message

1. Open your group in Buzz.
2. Type a message, for example: `hello, what can you do?`
3. Send it.
4. Wait a few seconds — Hermes will respond in the same channel.

Hermes processes your message, routes it through the Routstr LLM proxy to the AI model, and returns the response. Response time is typically 2-10 seconds depending on complexity.

### What Hermes can do

- **Answer questions** — general knowledge, coding help, research, writing
- **Create and manage tasks** — using the kanban system (Section 6)
- **Dispatch workers** — spin up sub-agents for parallel work (Section 7)
- **Run quality gates** — enforce testing and review standards (Section 8)
- **Schedule cron jobs** — recurring automated tasks
- **Read and write files** — within its workspace
- **Search the web** — for up-to-date information

### Conversation tips

- **Be specific** — "Write a Python script to parse a CSV file and output JSON" is better than "help with files".
- **Reference past context** — Hermes remembers the conversation within the same session. You can say "modify the script from earlier to also handle Excel files."
- **Ask for steps** — For complex tasks, ask Hermes to break it down: "Plan this in steps before starting."
- **Correct mistakes** — If Hermes gets something wrong, say so. It will adjust.

### Long messages

If you have a large request (a long document, multiple files, a detailed spec), paste it in a single message rather than many short ones. Hermes handles long messages well and it keeps context together.

---

## 6. Kanban Boards

Kanban is a task management system built into Hermes. It lets you create tasks, assign them to workers, and track progress through stages. You interact with kanban boards by messaging Hermes in the Buzz group.

### Creating a board

Message Hermes:

```
Create a kanban board called "website-redesign" with columns: todo, in-progress, review, done
```

Hermes will create the board and confirm. Each board is stored in a SQLite database on your Hermes instance.

### Creating tasks

```
Add a task to "website-redesign": "Write homepage HTML and CSS, must be responsive"
```

Hermes will create the task in the `todo` column. You can add multiple tasks in one message:

```
Add 3 tasks to "website-redesign":
1. Write homepage HTML and CSS, must be responsive
2. Set up deployment pipeline
3. Write integration tests for the contact form
```

### Moving tasks

Tasks move through columns as work progresses. Hermes moves them automatically when it works on them, but you can also direct it:

```
Move task "Write homepage HTML" to in-progress
```

### Checking board status

```
Show me the current state of "website-redesign"
```

Hermes will list all tasks and their columns, along with any comments or notes from workers.

### Task assignment

Each task can be assigned to a worker profile. By default, Hermes works on tasks itself. For parallel work, you can dispatch tasks to specialist workers (Section 7).

```
Assign task "Write integration tests" to worker-inspector
```

### Comments and notes

Tasks have comment threads for context. Workers and operators leave notes as they work:

```
Add a comment to "Write integration tests": "Use pytest with xdist for parallel test execution"
```

Comments are visible to all workers and persist across sessions.

---

## 7. Dispatching Workers

Workers are specialised sub-agents that Hermes can spawn to handle tasks in parallel. Each worker has its own conversation context, terminal session, and toolset. Workers are useful for long-running or complex tasks that should not block your main conversation.

### How dispatching works

1. You create a task on a kanban board (Section 6).
2. You tell Hermes to dispatch it to a worker.
3. Hermes spawns the worker with the task details.
4. The worker runs independently, reports progress, and completes the task.
5. You see the results in the kanban board and in the Buzz group.

### Dispatching a task

```
Dispatch task "Write integration tests" to worker-inspector
```

or

```
Spawn a worker to handle "Set up deployment pipeline" — assign to worker-admin
```

### Worker profiles

Your operator sets up worker profiles. Common profiles include:

- **worker-admin** — general-purpose worker, handles most tasks
- **worker-inspector** — quality control, reviews code and runs tests
- **researcher** — research and information gathering

Ask your operator which profiles are available on your instance.

### Parallel work

You can dispatch multiple tasks simultaneously:

```
Dispatch these tasks in parallel:
- "Write homepage HTML" to worker-admin
- "Set up deployment pipeline" to worker-admin
- "Write integration tests" to worker-inspector
```

Each worker runs in its own isolated context. They cannot see each other's work directly — coordination happens through the kanban board and task comments.

### Monitoring dispatched work

```
What's the status of dispatched tasks?
```

Hermes will report which workers are running, what they are doing, and any results they have returned. Long-running workers send periodic progress updates.

### When to use workers

- **Use a worker** for: long-running tasks (tests, builds, research), parallel independent work, tasks requiring a specialist profile.
- **Do not use a worker** for: quick questions, short answers, anything that takes under a minute. Just message Hermes directly.

---

## 8. Quality Gates

Quality gates are automated checks that run on code changes before they are considered complete. They enforce testing, review, and code quality standards. You do not need to set them up — they are pre-loaded into your Hermes instance.

### What quality gates check

1. **Tests pass** — all unit and integration tests must pass before a task is marked done.
2. **Code review** — a second worker (or model family) reviews the code for correctness and security.
3. **No secrets committed** — scanned to ensure no API keys, passwords, or tokens are in the code.
4. **Linting** — code follows style conventions (matches existing patterns in the codebase).
5. **Documentation** — new features require corresponding documentation updates.
6. **Commit discipline** — work is committed and pushed to git, not left uncommitted.
7. **Cross-family review** — for critical changes, a different AI model reviews the work for bias blind spots.

### How gates affect you

When you ask Hermes to build something, it runs the quality gates automatically before reporting completion. If a gate fails, Hermes will:

1. Report which gate failed and why.
2. Attempt to fix the issue automatically.
3. Re-run the gate.
4. Only report "done" when all gates pass.

### Reviewing gate results

```
Show me the quality gate results for the last task
```

Hermes will display each gate, its status (pass/fail), and any issues found.

### Blocking on review

Some changes require human review before merging. When this happens, Hermes will:

1. Leave a comment on the task with the details (changed files, test results, diff location).
2. Block the task from completing.
3. Notify you in the Buzz group that review is needed.

You then review the change and tell Hermes to proceed (or request changes).

### Why quality gates matter

They prevent common problems: untested code, security vulnerabilities, broken builds, and secret leaks. They ensure that work done by your Hermes instance is trustworthy and production-ready, not just plausible-looking.

---

## 9. Cashu Credits Flow

Cashu is a Bitcoin-based ecash system that handles AI credits. Your Hermes instance uses Cashu tokens to pay for LLM inference through the Routstr proxy. Credits are issued by your operator and consumed as you use the AI.

### How the flow works

```
Operator issues credits
    → Cashu mint marks quote as paid
    → Your Hermes instance mints tokens
    → Tokens spent at Routstr for each LLM call
    → Balance decreases per token of AI usage
```

### Checking your balance

```
How many AI credits do I have left?
```

Hermes queries the Routstr proxy for your current token balance and reports it. Balances are denominated in satoshis (sat), the smallest unit of Bitcoin.

### Getting more credits

When your balance runs low:

1. Message your operator in the Buzz group (or directly): "I am running low on AI credits."
2. The operator creates a mint quote on the Cashu mint.
3. The operator signs a Nostr approval event (kind 38010).
4. The mint-orchestrator daemon detects the approval and marks the quote as paid.
5. Your Hermes instance mints new tokens from the paid quote.
6. Your balance increases.

This process takes under a minute. The operator will confirm when credits have been issued.

### How credits are consumed

Each LLM call (every message you send to Hermes) costs a small number of sats based on:

- **Input tokens** — the size of your message plus conversation context
- **Output tokens** — the length of Hermes' response
- **Model used** — larger models cost more per token
- **Pricing margin** — set by the operator, covers infrastructure costs

Typical cost per message: 1-50 sats depending on complexity. A short question costs less than a long coding task.

### Credit limits

Your operator sets a monthly credit budget per friend. If you hit the limit:

- Hermes will warn you that credits are exhausted.
- LLM calls will fail until more credits are issued.
- Kanban tasks, file operations, and other non-LLM features continue to work.

Contact your operator to request a budget increase or wait for the monthly reset.

### Per-friend isolation

Each friend has their own API key in Routstr with its own quota. Your usage does not affect other friends' credits, and theirs does not affect yours. The operator manages all quotas centrally.

---

## 10. NIP-05 Identity Verification

NIP-05 is a Nostr standard for verifying that a Nostr identity belongs to a specific internet domain. It is similar to the blue checkmark on social media — it proves you control the domain associated with your npub.

### Why it matters

Without NIP-05, anyone can create a Nostr key and claim to be anyone. NIP-05 links your npub to a domain you control, letting others verify your identity. This matters for:

- **Trust** — other users can confirm you are who you say you are.
- **Relay access** — some relays use NIP-05 as an additional authentication factor.
- **Profile discovery** — NIP-05 verified profiles appear in directories and search.

### How NIP-05 works

A NIP-05 record is a JSON file hosted on a web domain at a well-known URL:

```
https://<your-domain>/.well-known/nostr.json?name=<username>
```

The file maps a username to an npub:

```json
{
  "names": {
    "alice": "npub1abcdef..."
  }
}
```

When a client (like Buzz) looks up `alice@your-domain`, it fetches this URL and checks that the npub matches.

### Setting up NIP-05 (if your operator provides it)

Your operator may offer NIP-05 verification through the infrastructure. If so:

1. Ask the operator to add your npub to the NIP-05 configuration.
2. Provide your preferred username (for example, `alice`).
3. The operator adds your entry to the `.well-known/nostr.json` file on the domain.
4. In Buzz, go to your profile settings and set your NIP-05 identifier to `alice@your-domain`.
5. Buzz will verify the identifier. If it matches, you get a verified badge.

### Setting up NIP-05 (on your own domain)

If you have your own domain:

1. Create a directory `.well-known/` on your web server.
2. Create a file `nostr.json` with your npub:

```json
{
  "names": {
    "yourname": "npub1yournpubhere..."
  }
}
```

3. Serve it at `https://yourdomain.com/.well-known/nostr.json` with CORS headers (`Access-Control-Allow-Origin: *`).
4. In Buzz, set your NIP-05 identifier to `yourname@yourdomain.com`.
5. Verify in Buzz settings.

### Verifying it works

Once configured, your profile in Buzz (and any Nostr client) will show a verified checkmark next to your NIP-05 identifier. Other users can look you up by `yourname@yourdomain.com` instead of copying your npub.

### Troubleshooting NIP-05

- **Not verifying**: Check that the JSON file is accessible at the correct URL in a browser. Check CORS headers are set. Verify the npub in the file matches your npub exactly.
- **Wrong domain**: The domain in your NIP-05 identifier must match the domain hosting the `.well-known/nostr.json` file.
- **Cached old result**: Some clients cache NIP-05 lookups. Restart Buzz to force a re-check.

---

## Quick Reference

| What | Where | How |
|---|---|---|
| Chat client | Buzz desktop app or `https://chat.<domain>` | Install, connect to relay |
| Relay URL | `wss://relay.<domain>` | Add in Buzz relay settings |
| Authentication | NIP-42 (automatic) | Whitelist your npub with operator |
| Group chat | NIP-29 group in Buzz | Operator adds your npub to group |
| AI assistant | Message in group | `@botname <your message>` |
| Task management | Kanban boards via Hermes | `Create a kanban board called "..."` |
| Workers | Dispatch via Hermes | `Dispatch task "..." to worker-admin` |
| Quality gates | Automatic on code tasks | `Show quality gate results` |
| AI credits | Cashu via Routstr | `How many credits do I have?` |
| Identity | NIP-05 on your domain | Set in Buzz profile settings |

---

## Getting Help

If something is not working:

1. Check the relevant section of this guide.
2. Ask in the Buzz group — your operator and Hermes bot are both there.
3. For infrastructure issues (relay down, credits not working, container crashes), message your operator directly.

Your operator has access to server logs, container status, and the mint configuration. Most issues are resolved by the operator restarting a service or adjusting a configuration.

---

*This guide is part of the Tollgate Infrastructure Kit. For the operator-facing documentation, see [Getting Started](getting-started.md) and [Configuration Reference](configuration.md).*