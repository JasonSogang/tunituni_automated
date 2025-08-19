# Project: SahaSCC Application Automation (Parent–Child Program)

## Overview
This project automates submitting an application on the SahaSCC website when the status changes from “신청예정” to “신청”. The automation minimizes latency at open time, handles follow-up events (alerts, popups, iframes, and dynamic forms), and saves rich logs for postmortem analysis. It is designed to be resilient even when the exact form structure is unknown ahead of time.

Target page (child program example):
- `https://www.sahascc.or.kr/parent/Appchild_view.asp?sn=108`

Environment/timezone:
- The host system time is KST (UTC+09:00). You can pass an open time: `--start-at 'YYYY-MM-DDTHH:MM:SS'` (KST).

## Goals
- Automatically detect when “신청” becomes available and submit rapidly.
- Follow through unknown post-click events (alerts, redirects, popups/new windows, iframes).
- Heuristically fill and submit forms without prior exact field mapping.
- Capture detailed logs (DOM and network) to diagnose any failures and harden future runs.
- Be resilient to Chrome/ChromeDriver glitches and intermittent site throttling.

## Resilience Hardening (Latest)
- Popup suppression: forces `window.open` and `target=_blank` to same-tab via injected JS, eliminating fragile window switching in headless.
- Consent automation: clicks `#chkall` if present and ensures `agree1/2/3=Y` radios selected.
- Submit triggers: detects and clicks `javascript:checkIt()` anchors and common submit buttons; last-resort JS `document.myform.submit()` if needed.
- Direct-apply attempts: after start, also tries flagged endpoints like `?apply=1`, `?mode=apply`, and `Appchild_regist.asp?sn=<sn>`.
- Driver disconnect resilience: wraps window-handle/refresh calls, adds keepalive JS per loop, and auto-restarts the driver/session up to `--max-restarts` times upon connection loss.
- Rate-limit backoff: exponential backoff (12s → up to 60s) when the site responds with “too many requests/요청이 많…”.
- Version safety: logs Chrome and ChromeDriver versions at startup; warns on major mismatch.
- Driver discovery: prefers PATH `chromedriver`, then bundled `venv/chromedriver-Linux64`, then Selenium’s default resolution.
- Event timeline: writes concise, flushed timeline logs to `logs/events_*.log` for mid-run diagnosis even if a crash occurs.
- Success verification: visits MyPage and matches by `sn`, as well as parent/child names; writes `logs/verify_summary.json` with a compact result.

## Key Scripts

### 1) `resilient_bot.py` (main automation)
- Configuration:
  - Credentials and user data (parent/child names, birth date, months, phone, email, address, gender) are set near the top of the script.
  - Target: `TARGET_URL` points to a given program (e.g., `sn=108`). Can be overridden with `--target-url`.
  - Start time: `START_AT` controls when to begin aggressive polling. Can be overridden with `--start-at`.

- Waiting strategy:
  - Before the pre-window: sleep until 5 minutes before open.
  - During long wait, refresh every 10 minutes and log remaining time to pre-window and open.
  - Aggressive phase (T-5m to T+5m): refresh every ~5 seconds (±1s jitter) and try to detect/click the real “신청”.

- Clicking and follow-up:
  - Detects true controls (excludes “신청예정”).
  - Accepts alert/confirm immediately.
  - Suppresses popups (forces same-tab); still attempts iframe switching if forms are inside.

- Direct apply flags (post-start):
  - If the normal path does not expose a form, navigates directly to: `?apply=1`, `?mode=apply`, and `Appchild_regist.asp?sn=<sn>`.

- Heuristic form filling & consent:
  - Maps by `name/id/placeholder/label` keywords for typical fields.
  - Auto-consent: clicks “동의/약관/개인정보/agree” checkboxes; selects agree radios; if `#chkall` exists, uses it to select all.
  - Submits via “신청/접수/제출/등록/확인” buttons and `javascript:checkIt()` anchors; last resort: JS `myform.submit()`.

- CAPTCHA & rate-limit handling:
  - Detects reCAPTCHA/generic captchas; on detection: saves `logs/captcha_page.{html,png}`, backs off 30s.
  - Rate-limit: exponential backoff from ~12s up to 60s when such alerts occur.

- Success verification:
  - Visits `/mypage/Appchild.asp` and checks signals: `sn=<sn>`, rows containing `sn`, parent/child name matches. Saves `logs/verify_mypage.{html,png}` and `logs/verify_summary.json`.

- Driver resilience & logging:
  - Driver auto-restart upon disconnect (up to `--max-restarts`).
  - Keepalive JS to detect silent drops.
  - Startup logs browser/driver versions and warns on major mismatch.
  - Event timeline logs: `logs/events_*.log`. HAR-like logs via Chrome performance log: `logs/har_<epoch>.jsonl`.

### 2) `probe_flow.py` (instrumented click probe)
- Logs into the site, navigates to the target view, and when a real “신청” is present:
  - Clicks it, handles alerts, switches windows/iframes, enumerates forms.
  - Saves HTML (`logs/probe_*_post.html`), screenshot, and JSON metadata.

### 3) `preflight_mapper.py` (pre-open endpoint exploration)
- Logs in (via Selenium) and replays the session using `requests`.
- Probes a wide range of likely endpoints across `parent/` and `mypage/` folders, combining:
  - Base names: `Appchild`, `AppChild`, `appchild`, etc.
  - Suffixes: `_write/_apply/_form/_input/_proc/_ok/_insert/_reg/_request/_submit/_join/_regist/_regist_ok` (+ capitalized variants).
  - Also tests `Appchild_view.asp?sn=...&apply=1|mode=apply`.
- Saves interesting HTML samples as `logs/preflight_*_*.html` and a summary JSON `logs/preflight_map_*.json`.

### 4) `open_item_scanner.py` (open-item reconnaissance)
- Logs in and scans multiple listing pages (Appchild/AppParent/Playroom/Culture/Rainbow/Time-list).
- If listing has a visible “신청/신청하기/예약/접수” control, clicks it; otherwise it discovers detail links (`*_view.asp?sn=...`) and probes each detail page’s `.btn-grp`.
- Captures alerts, URL after click, forms (action/method/fields/buttons), and saves HTML/screenshot/HAR logs.
- Useful to harden automation before D-Day using currently “open” items on the site (even from other sections using the same engine/template).

### 5) Console tracers (optional manual instrumentation)
- `console_apply_observer.txt` / `console_apply_tracer.txt`:
  - Paste into the browser DevTools Console (Preserve log ON) to record the appearance/click of “신청” controls, alerts, window.open URLs, history navigation, fetch/XHR endpoints, and form submissions.
  - Intended for manual rehearsal; the main automation already stores HAR/HTML.

## Configuration
- Credentials (in `resilient_bot.py`):
  - `USERNAME`, `PASSWORD`
- Target:
  - `TARGET_URL` default can be overridden with `--target-url`.
  - `START_AT` default can be overridden with `--start-at`.
- User data sample (in `resilient_bot.py`):
  - Parent: name, phone, email, address.
  - Child: name, birth (YYYY-MM-DD), age in months, gender.
- Driver selection order:
  - PATH `chromedriver` → `venv/chromedriver-Linux64` (bundled) → Selenium default discovery.
- Browser/driver versions are logged at startup; major mismatches will be warned in `events` log.

## Runtime Behavior Summary
1) Login and navigate to `TARGET_URL`.
2) Wait until 5 minutes before open; refresh every 10 minutes; log remaining time.
3) From T-5m to T+5m:
   - Refresh ~every 5 seconds (±1s jitter); detect and click the real “신청”.
   - Accept alerts; suppress popups (same-tab); switch iframes if necessary.
   - On/after open, if no form is visible, try `?apply=1`, `?mode=apply`, and `Appchild_regist.asp?sn=<sn>`.
4) Heuristically fill forms and submit (consent radios/checkboxes/*chkall*/agree fields included). Tries `checkIt()` anchors and last-resort JS submit.
5) Save `submission_result.html`, HAR logs; verify success in `/mypage/Appchild.asp` and save `logs/verify_mypage.{html,png}`, `logs/verify_summary.json`.
6) On captcha detection: save `logs/captcha_page.{html,png}`, back off 30s. On rate-limit alerts: exponential backoff (12s→60s).

## How To Run
- Main automation (headless):
  - `python3 resilient_bot.py`
- UI rehearsal (see popups/alerts live):
  - `python3 resilient_bot.py --no-headless --target-url '<DETAIL_URL>'`
- Schedule relative to open time (KST):
  - `python3 resilient_bot.py --start-at 'YYYY-MM-DDTHH:MM:SS' --target-url '<DETAIL_URL>'`
- Increase driver auto-restarts on disconnect (optional):
  - `python3 resilient_bot.py --start-at '...' --target-url '...' --max-restarts 3`
- Pre-open mapping (optional):
  - `python3 preflight_mapper.py`
- Open-item reconnaissance (optional):
  - `python3 open_item_scanner.py`
- Probe instrumentation (optional):
  - `python3 probe_flow.py`

## Version Check Utility
- `check_versions.py` prints both the Browser and ChromeDriver versions the environment will use.
  - Run: `python3 check_versions.py`
  - If major versions differ (e.g., 139 vs 138), replace the driver with a matching major (e.g., put it at `venv/chromedriver-Linux64` and make it executable).

## Known Patterns and Findings
- The site often reuses the same “detail-view” template for applications instead of separate `*_apply.asp` pages.
- Direct flags on the view page frequently work: `?apply=1`, `?mode=apply`.
- Parent flows revealed a “regist” pattern (e.g., `AppParent_regist.asp` → `AppParent_regist_ok.asp`).
  - The child flow mirrors this with `Appchild_regist.asp?sn=...` → `Appchild_regist_ok.asp`.
  - A “checkIt()” JS anchor is commonly used for submission after verifying `agree1/2/3`.

## Limits and Notes
- 100% guarantees are not possible if the site introduces new CAPTCHA, payment gates, or queue systems at runtime, or if Chrome/Driver bugs occur.
- Current approach handles normal flows and stores sufficient logs to quickly harden future runs.
- CAPTCHA is not solved automatically; it is detected, logged, and a backoff is applied. Run with `--no-headless` for manual solve if needed.

## Future Enhancements (optional)
- Manual-intervention mode for CAPTCHA (pause, user solves, then continue).
- Stronger success verification (parse latest rows in MyPage application list with structured selectors).
- Adaptive backoff and multi-instance coordination to further reduce risk of rate-limiting.
- Structured DOM snapshots for diff-based troubleshooting.
