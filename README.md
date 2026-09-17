# tweet-watch-bot

A Telegram bot that watches X (Twitter) accounts via [twitterapi.io](https://twitterapi.io)
and forwards new tweets into the chat that asked for them.

## Commands

| Command | What it does |
|---|---|
| `/watch https://x.com/handle` | Start watching an account. Takes a baseline immediately (no flood of old tweets — only tweets posted *after* this point are sent). |
| `/unwatch https://x.com/handle` | Stop watching an account in this chat. |
| `/watching` | List the accounts currently watched in this chat. |

## How it works

- One background loop cycles through every distinct handle being watched
  (across all chats) and calls `GET /twitter/user/last_tweets` on twitterapi.io.
- There's a **5.5 second gap between every individual API call**, tuned for
  the twitterapi.io free tier. If you're watching `N` handles, one full
  cycle takes roughly `N × 5.5s` — so on the free tier, watching a lot of
  accounts means each one is checked less often. Raise `POLL_GAP_SECONDS`
  if you upgrade your plan, or lower it (but note the free-tier limit).
- Each handle is only ever fetched **once per cycle**, even if multiple
  chats are watching it — new tweets are then fanned out to every chat
  subscribed to that handle.
- State (which chat watches which handle, and the last tweet id seen per
  handle) is kept in a local SQLite file (`watchlist.db` by default).

## 1. Create your bot & get keys

1. **Telegram bot token**: message [@BotFather](https://t.me/BotFather) on
   Telegram, run `/newbot`, and copy the token it gives you.
2. **twitterapi.io API key**: sign up at https://twitterapi.io/dashboard
   and copy your API key from the dashboard.

## 2. Run it locally (optional, to test first)

```bash
git clone <your-repo-url>
cd tweet-watch-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your real tokens
export $(cat .env | xargs)   # or use a tool like python-dotenv / direnv
python main.py
```

Then open Telegram, find your bot, and send `/watch https://x.com/nasa`.

## 3. Push to GitHub

```bash
cd tweet-watch-bot
git init
git add .
git commit -m "Initial commit: tweet watch bot"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

`.env` is already in `.gitignore` — never commit your real tokens.

## 4. Deploy on Railway

1. Go to [railway.com](https://railway.com), **New Project → Deploy from GitHub repo**,
   and pick the repo you just pushed.
2. Railway will auto-detect Python via Nixpacks and use `railway.json` /
   `Procfile` to run `python main.py` as a worker (no public port needed,
   since this bot uses long-polling, not a webhook).
3. Open the service's **Variables** tab and add:
   - `TELEGRAM_BOT_TOKEN`
   - `TWITTERAPI_IO_KEY`
   - (optional) `POLL_GAP_SECONDS` — defaults to `5.5`
   - (optional) `DB_PATH` — see the persistence note below
4. Deploy. Check the **Deploy Logs** for `Starting poll loop…` to confirm
   it's running.

### Persisting the watch list across redeploys

Railway's default filesystem is ephemeral — it survives restarts but is
wiped on a fresh deploy/rebuild. If you want your `/watch` list to survive
redeploys:

1. In the Railway service, add a **Volume** (Settings → Volumes) and mount
   it at, e.g., `/data`.
2. Set the `DB_PATH` variable to `/data/watchlist.db`.

Without a volume, the bot still works fine — you'd just need to re-run
`/watch` for each handle after a redeploy.

## Notes

- If a handle doesn't exist or twitterapi.io returns an error, `/watch`
  will tell you immediately instead of silently failing.
- Forwarded messages include the tweet author, full text, and a link back
  to the tweet on X.
- This bot doesn't need a webhook or public URL — it long-polls Telegram,
  which is why it's set up as a Railway "worker" rather than a "web" service.
