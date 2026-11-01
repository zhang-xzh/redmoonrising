---
name: eve-online-university-wiki
description: Use when you need EVE Online game knowledge absent from the 3913 client and RMR code - mechanics, ships, PvE/PvP, industry. Triggers: EVE University, EVE University Wiki
---

# EVE University Wiki lookup

`wiki.eveuniversity.org` is the community player wiki (MediaWiki) for EVE Online game knowledge. Use it for **how the game works** — not for RMR's own runtime/data questions (those are answered from `crates/eve-server`, `db/`, and `doc/`).

- Page URL: `https://wiki.eveuniversity.org/<Page_Name>` — spaces become underscores, e.g. `Fitting` → `https://wiki.eveuniversity.org/Fitting`.
- API endpoint: `https://wiki.eveuniversity.org/api.php` (read-only, no auth).
- Prefer **WebFetch** for a single page's prose; use the **API** when you need raw wikitext, structured lists (categories/links), or search across pages.

## 0. Accuracy caveat (important for RMR)

The wiki describes **modern** EVE; this project targets build 3913 (2006). Mechanics, ship stats, module attributes, market rules and UI have all changed since. Treat the wiki as a source for *concepts and vocabulary*, never as the value source for RMR:

- Values must come from the 3913 client (`M:\EVE-LOCAL\inputs\EVE-Online-3913`) or `db/*.sql.gz`.
- Where the 2006 client and the wiki disagree, the client wins (see `AGENTS.md`「零售版本优先」).

## 1. Search

```powershell
curl.exe -s "https://wiki.eveuniversity.org/api.php?action=query&list=search&srsearch=machoNet&srlimit=5&format=json&formatversion=2" |
  jq -r '.query.search[] | [.title, .wordcount, .timestamp] | @tsv'
```

- `srsearch` accepts the same syntax as the wiki search box (quotes, `intitle:`, `incategory:`).
- Paging: pass the returned `continue.continue` as `sroffset` until it disappears.

## 2. Read a page

```powershell
curl.exe -s "https://wiki.eveuniversity.org/api.php?action=query&prop=extracts&explaintext=1&exintro=1&titles=Fitting&format=json&formatversion=2" |
  jq -r '.query.pages[0].extract'
```

Full page as wikitext (tables/infoboxes/links):

```powershell
curl.exe -s "https://wiki.eveuniversity.org/api.php?action=parse&page=Fitting&prop=wikitext&format=json&formatversion=2" |
  jq -r '.parse.wikitext'
```

- Drop `exintro=1` for the whole article; `&section=N` for one section (0-based intro).
- `formatversion=2` gives cleaner JSON.

## 3. Walk categories and links

```powershell
curl.exe -s "https://wiki.eveuniversity.org/api.php?action=query&list=categorymembers&cmtitle=Category:Ships&cmlimit=50&format=json&formatversion=2" |
  jq -r '.query.categorymembers[].title'
```

Sub-categories only: `&cmtype=subcat`; pages only: `&cmtype=page`.

## 4. Common entry points

| Topic | Page / category |
|---|---|
| Game mechanics hub | `Mechanics` |
| Ship list / classes | `Category:Ships`, `Alphabetical Ship List` |
| Fitting & skills | `Category:Fitting`, `Category:Skills` |
| PvE missions & agents | `Category:PvE`, `Category:Missions` |
| Industry & PI | `Category:Industry`, `Planetary Industry` |
| PvP tactics | `Category:PvP` |
| NPC factions/damage | `Category:NPCs` |
| History (2003–2006 era) | `Category:History`, expansion pages |

Search first — page names change.

## 5. Etiquette / limits

- Send a descriptive `User-Agent` if you script bulk requests; keep concurrency to 1–2 and rate low. Read-only GETs only.
- Cache the page you fetched in your reasoning; do not re-fetch the same title per turn.

## 6. Related

- Local first: `doc/knowledge-inventory.md` and `doc/platform/architecture.md`.
- Exact 2006 values: the 3913 client (`res\*.stuff`, `script\compiled.code`) and `db/*.sql.gz` — not the wiki.

## 触发关键词

EVE University, EVE University Wiki, wiki.eveuniversity.org, EVE wiki, 查询 EVE 维基, EVE 资料, EVE 攻略, EVE 机制, 舰船配置, 游戏机制, 2006 EVE, 老版本 EVE
