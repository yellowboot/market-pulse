# Investor platform — concept document

> Living document. Updated as the project evolves.
> Last updated: 2026-07-13

---

## 1. Product idea

A single platform for the retail investor: news, portfolio analytics, and useful tools — part free, core functionality via an affordable subscription.

**Who it's for:** retail investors who track their portfolio manually (Excel, notes, scattered broker apps) and want everything in one place.

**How it differs from competitors:** built by an investor for themselves, not by an abstract product manager — features grow out of real pain points, not marketing hypotheses.

---

## 2. Product modules

### 2.1 News module (open access)
- RSS parsing from financial sources
- Filtering by sector / source
- Smart matching of news to tickers (linking a news item to a specific stock from the portfolio/watchlist)
- **Status:** prototype ready (Python + HTML, dark theme)

### 2.2 Investor tools (subscription)
- **Portfolio tracking** — positions, value, asset class allocation
- **Return calculator** — return calculation accounting for deposits/withdrawals
- **Dividend tracking** — payout tracking, future dividend forecasts, dividend calendar
- **Watchlist with target prices** — tracking buy candidates, price alerts
- **Compound interest calculator** — portfolio growth projection
- **Status:** React "Investor Journal" prototype ready, needs merging with the other modules

### 2.3 Investor account
- Sign-up / authentication
- User data storage (portfolio, watchlist, settings)
- Subscription management
- **Status:** not started

### 2.4 Future directions (not now, noted for the record)
- Broker API integrations (Revolut, Interactive Brokers, etc.) — automatic portfolio sync
- Advanced analytics (risk metrics, diversification)
- AI news summaries / price-move explanations
- B2B version for fintech companies

---

## 3. How the modules connect

```
News module ──┐
              ├──> Personalization (matching news to tickers from portfolio/watchlist)
Portfolio ────┘

Portfolio ──> Return calculator
Portfolio ──> Dividend tracking ──> Dividend calendar
Watchlist ──> Target-price alerts ──> (future) link to news "why it dropped"

Account ──> stores all user data ──> ties all modules together
```

**Key idea:** the account is the core the other modules revolve around. Without it, everything stays disconnected (as it is now — separate prototypes).

---

## 4. Monetization model

| Tier | Access | Price |
|---|---|---|
| Free | News module (basic), limited watchlist | €0 |
| Subscription | Full functionality: portfolio, dividends, calculators, unlimited watchlist | affordable, TBD (~€5–10/mo) |

---

## 5. Tech stack (current)

- **Backend/scripts:** Python (RSS parsing, data processing)
- **Frontend:** React + HTML/CSS (dark luxury theme)
- **Data:** local for now, database + server in the future
- **Hosting:** not chosen yet

---

## 6. Roadmap

### Now
- [ ] Consolidate the 3 existing prototypes into a single repo structure
- [ ] Publish to GitHub with documentation

### Next
- [ ] Design the account system (basic auth)
- [ ] Merge portfolio + dividends + calculators into a single interface
- [ ] Link news to tickers from the user's portfolio

### Later
- [ ] Subscription model (payments)
- [ ] Public launch for first users
- [ ] Broker integrations

---

## 7. Decision and change log

_Key decisions will be logged here as the project evolves — what changed and why._

- **2026-07-13:** Locked in the overall concept: a single product combining the news module + investor tools + account, monetized via an affordable subscription.
