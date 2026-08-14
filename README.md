<p align="center">
  <img src="assets/banner.jpg" alt="Market Pulse" width="100%">
</p>

# Market Pulse — stock market news aggregator

## Live version

The site updates itself, no human involved: GitHub Actions runs `fetch_news.py` on a schedule (every ~90 minutes on weekdays, with a 30+ minute buffer before open and after close of NYSE/Nasdaq trading in both summer and winter; once a day on weekends — see `.github/workflows/update-news.yml`), commits the fresh `news_data.js` back to the repo, and GitHub Pages immediately serves the updated page. Open the site in a browser and you just see the finished result — nothing to run by hand.

## What's included
- **fetch_news.py** — a pure-Python script (no pip install needed) that pulls news from public RSS feeds, scores sentiment by keywords, and tags tickers from your watchlist.
- **news_dashboard.html** — the page itself, a dark luxury theme with gradients. Open it with a regular double-click, or view it live on the site (see above).
- **news_data.js** — the data file the script generates. The repo ships with a snapshot of real news from publish time; GitHub Actions overwrites it on every run after that.
- **.github/workflows/update-news.yml** — the feed's auto-update schedule (GitHub Actions).

## Local run (optional)
The following is for anyone who wants their own copy (their own watchlist, their own feeds) or just prefers running locally instead of the live GitHub Pages version.

1. Make sure Python 3 is installed (check with `python3 --version`).
2. In a terminal, go to the folder with the files:
   ```
   cd path/to/news_aggregator
   ```
3. Run the fetcher:
   ```
   python3 fetch_news.py
   ```
   It pulls fresh news and rewrites `news_data.js`.
4. Open `news_dashboard.html` in a browser (or refresh the tab if it's already open).

## Refreshing data (for a local copy)
The live version on GitHub Pages updates itself (see "Live version" above) — this section only applies to a local copy.

Whenever you want fresh news, just run `python3 fetch_news.py` again and hit F5 on the page. No server needed.

To automate a local copy (e.g. refresh every hour):
- **macOS/Linux:** add a line like this to `crontab -e`:
  `0 * * * * cd /path/to/folder && python3 fetch_news.py`
- **Windows:** create a Task Scheduler task that runs
  `python3 fetch_news.py` in this folder once an hour.

## LLM sentiment/importance classification (optional)

By default, sentiment and importance are scored with a local keyword heuristic — fast, free, but it doesn't understand context (e.g. "sanctions lifted" could wrongly land in "negative" just because "drops" is a generally negative word).

For more accuracy, you can plug in [DeepSeek](https://platform.deepseek.com) (`deepseek-chat`, DeepSeek-V3) — one of the cheapest APIs on the market, with more than enough quality for news classification, and it actually understands what a headline means instead of just matching words.

**If the key isn't set or the request fails** (no internet, quota hit, network blocked it) — the script quietly falls back to the plain heuristic, nothing breaks.

**Cost.** News items are sent in batches of 15. A full run (~80 items → 6 requests) costs a fraction of a cent — even with hourly auto-updates during market hours, that's pennies a month. Current pricing is at [platform.deepseek.com](https://platform.deepseek.com/api-docs/pricing). You can also set a spend cap on the key on the platform, just in case.

### ⚠️ The key belongs only in GitHub Secrets, never in code

An API key is a secret. It must never end up in repo files, commits, workflow logs, or anywhere someone other than you could see it. `fetch_news.py` reads it **only** from the `DEEPSEEK_API_KEY` environment variable — there is no key in the code, and there never should be.

**How to get a key:**
1. Sign up at [platform.deepseek.com](https://platform.deepseek.com) and add a payment method.
2. In the API Keys section, create a new key and copy it — DeepSeek only shows it once.

**How to safely add the key for GitHub auto-updates** (no one, including an AI assistant in chat, needs to see the key):

Run this in your own terminal (not through a chat assistant!):
```
gh secret set DEEPSEEK_API_KEY --repo yellowboot/market-pulse
```
It'll prompt you to paste the key value — type it straight into the terminal and hit Enter. The value goes directly into GitHub's encrypted storage; it won't be echoed to the screen and won't end up in command history or logs.

No-terminal alternative: GitHub → your repo → **Settings → Secrets and variables → Actions → New repository secret** → name `DEEPSEEK_API_KEY`, value — the key itself.

After that, `.github/workflows/update-news.yml` picks up the secret automatically on the next run — nothing else to configure.

**For a local run** (outside GitHub), set the key as a regular environment variable before running:
- **macOS/Linux:**
  ```
  export DEEPSEEK_API_KEY="your-key"
  python3 fetch_news.py
  ```
- **Windows (cmd):**
  ```
  set DEEPSEEK_API_KEY=your-key
  python fetch_news.py
  ```
To avoid typing this every time, save the environment variable at the system level (see above) — it'll then also be picked up by `run_news.bat`/`run_news.command`. The key only ever lives in your machine's environment variables — it's never written to project files.

## If news doesn't load
Possible causes:
- An RSS provider is temporarily down or changed its feed address — the console will print which feed didn't respond.
- No internet connection at run time.
- Some networks/proxies block access to specific domains.

The feed list is at the top of `fetch_news.py`, in the `FEEDS` variable. Easy to add, remove, or reorder.

## Running without a terminal

### Option 1 (recommended): a launcher file — just double-click
- **Windows:** double-click `run_news.bat`. It fetches the news and opens the dashboard for you.
- **macOS:** double-click `run_news.command`.
  If macOS refuses to run it ("unidentified developer"): right-click → "Open" → confirm once, and after that it'll open with a regular double-click.

Pros: nothing to build or install, works right away, files are visible and easy to tweak anytime.
Cons: Python 3 still needs to be installed on the machine (usually already there on Mac; on Windows it's a one-time 3-minute download from python.org).

### Option 2: a real .exe (no Python on the machine)
If you want a single .exe with no dependencies at all, build it yourself with PyInstaller **on a Windows machine**:
```
pip install pyinstaller
pyinstaller --onefile --console --name MarketPulse fetch_news.py
```
The resulting file appears in the `dist\MarketPulse.exe` folder. Place it next to `news_dashboard.html` and run it instead of the script — it updates `news_data.js` the same way.

Keep in mind:
- The exe will be fairly large (15-40 MB) because it bundles the entire Python interpreter.
- Antivirus software sometimes flags PyInstaller-built exes as suspicious — that's a known quirk of the packager, not a sign the script itself is malicious. If Windows Defender flags the file, you can add an exclusion.
- If you later want to change the RSS feed list or watchlist, you'll need to edit `fetch_news.py` and rebuild the exe. Option 1 (launcher) is more flexible in that regard.

## Possible future improvements
- Custom icon for the .exe (PyInstaller's `--icon=path.ico` flag).
- A personal watchlist without editing code (currently edited in `COMPANY_MAP` inside `fetch_news.py`).
