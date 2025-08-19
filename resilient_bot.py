import os
import sys
import time
import random
import shutil
import re
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    WebDriverException,
)


# ====== USER CONFIG (hardcoded) ======
LOGIN_URL = "https://www.sahascc.or.kr/member/login.asp"
TARGET_URL = "https://www.sahascc.or.kr/parent/Appchild_view.asp?sn=108"

# Credentials (edit these)
USERNAME = "kfqsangwoo"
PASSWORD = "1wndeowkd1!"

# Optional start time in ISO format. Empty string to start immediately.
START_AT = "2025-08-19T10:00:00"  # KST

# User data for heuristic form filling (edit as needed)
USER_DATA = {
    "name": "조상우",
    "child_name": "조아론",
    "child_age": "40",
    "phone": "010-7149-7772",
    "email": "cjthemax@gmail.com",
    "child_birth": "2022-04-13",  # YYYY-MM-DD or YYYYMMDD
    "address": "부산광역시 사하구 승학로71번길 30 당리푸르지오아파트 103동 904호",
    "child_gender": "남",
}
# =====================================

EVENTS_LOG_PATH = None

def _init_event_log():
    global EVENTS_LOG_PATH
    try:
        os.makedirs("logs", exist_ok=True)
        ts = int(time.time())
        EVENTS_LOG_PATH = os.path.join("logs", f"events_{ts}.log")
    except Exception:
        EVENTS_LOG_PATH = None


def evt(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    if not EVENTS_LOG_PATH:
        return
    try:
        with open(EVENTS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def _append_query(url: str, extra: str) -> str:
    if "?" in url:
        if url.endswith("?") or url.endswith("&"):
            return url + extra
        return url + ("&" + extra)
    return url + ("?" + extra)


def inject_same_tab_policy(driver) -> None:
    """Force window.open and target=_blank to stay in same tab to avoid popup switching in headless."""
    js = r"""
    try {
      if (!window.__forceSameTab__) {
        window.__forceSameTab__ = true;
        const origOpen = window.open;
        window.open = function(url){ try { if (url) { window.location.assign(url); } } catch(e) {} return null; };
        document.addEventListener('click', function(e){
          const a = e.target && e.target.closest && e.target.closest('a[target="_blank"]');
          if (a && a.href) { e.preventDefault(); try { window.location.href = a.href; } catch(e) {} }
        }, true);
      }
    } catch (e) {}
    """
    try:
        driver.execute_script(js)
        evt("[nav] Applied same-tab policy (suppress popups)")
    except Exception:
        pass


def build_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()
    # Headless new is more stable with Chrome >= 109
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    )
    # Enable performance + browser logs (HAR-like capture)
    try:
        opts.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
    except Exception:
        pass

    # Prefer chromedriver from PATH or common locations
    chromedriver_path = shutil.which("chromedriver") or "/usr/bin/chromedriver"
    # Also allow bundled drivers in workspace venv
    workspace_candidates = [
        os.path.join(os.getcwd(), "venv", "chromedriver-Linux64"),
        os.path.join(os.getcwd(), "venv", "chromedriver"),
    ]
    for p in [chromedriver_path] + workspace_candidates:
        try:
            if p and os.path.exists(p):
                service = Service(p)
                return webdriver.Chrome(service=service, options=opts)
        except Exception:
            continue
    # Fallback: try default discovery
    return webdriver.Chrome(options=opts)


def wait_alert_and_accept(driver, timeout=5) -> Optional[str]:
    try:
        WebDriverWait(driver, timeout).until(EC.alert_is_present())
        alert = driver.switch_to.alert
        txt = alert.text
        alert.accept()
        return txt
    except Exception:
        return None


def ensure_login(driver, username: str, password: str, timeout=20) -> None:
    if not username or not password:
        raise RuntimeError("USERNAME/PASSWORD not set in script")

    driver.get(LOGIN_URL)
    WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.NAME, "userid")))
    driver.find_element(By.NAME, "userid").clear()
    driver.find_element(By.NAME, "userid").send_keys(username)
    driver.find_element(By.NAME, "Pass").clear()
    driver.find_element(By.NAME, "Pass").send_keys(password)

    # There appear to be two submit inputs; click the second when present
    submit_buttons = driver.find_elements(By.XPATH, "//input[@type='submit']")
    (submit_buttons[1] if len(submit_buttons) >= 2 else submit_buttons[0]).click()

    msg = wait_alert_and_accept(driver, timeout=5)  # handle potential confirm/alert
    if msg:
        evt(f"[login] alert: {msg}")
    WebDriverWait(driver, timeout).until(EC.url_changes(LOGIN_URL))
    evt("[login] OK")


def adaptive_sleep_until(start_dt: datetime) -> None:
    # Sleep with increasing precision near the deadline
    while True:
        now = datetime.now()
        if now >= start_dt:
            return
        remaining = (start_dt - now).total_seconds()
        if remaining > 300:
            time.sleep(60)
        elif remaining > 60:
            time.sleep(10)
        elif remaining > 10:
            time.sleep(2)
        else:
            time.sleep(0.25)


def _fmt_remaining(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def wait_until_with_refresh(
    driver,
    target_dt: datetime,
    refresh_interval_sec: int = 600,
    start_dt: Optional[datetime] = None,
) -> None:
    """Wait until target_dt, refreshing every refresh_interval_sec, and log remaining only on refresh.
    start_dt is the actual open time (for logging remaining until open); if None, only target remaining is shown.
    """
    now = datetime.now()
    remain_target0 = (target_dt - now).total_seconds()
    remain_open0 = (start_dt - now).total_seconds() if start_dt else None
    msg0 = f"[wait] Remaining to pre-window: {_fmt_remaining(remain_target0)}"
    if remain_open0 is not None:
        msg0 += f" | to open: {_fmt_remaining(remain_open0)}"
    print(msg0)

    last_refresh = time.time()
    next_refresh = last_refresh + max(1, refresh_interval_sec)
    while True:
        now = datetime.now()
        if now >= target_dt:
            return
        remain_target = (target_dt - now).total_seconds()
        remain_open = (start_dt - now).total_seconds() if start_dt else None

        if time.time() >= next_refresh:
            try:
                driver.refresh()
            except Exception:
                pass
            msg = f"[wait] Refreshed. Remaining to pre-window: {_fmt_remaining(remain_target)}"
            if remain_open is not None:
                msg += f" | to open: {_fmt_remaining(remain_open)}"
            print(msg)
            last_refresh = time.time()
            next_refresh = last_refresh + max(1, refresh_interval_sec)


        # Choose a small sleep step but wake up before next refresh
        if remain_target > 300:
            base = 60
        elif remain_target > 60:
            base = 10
        elif remain_target > 10:
            base = 2
        else:
            base = 0.25
        sleep_for = min(base, max(0.05, next_refresh - time.time()))
        time.sleep(sleep_for)


def find_apply_element(driver) -> Optional[webdriver.remote.webelement.WebElement]:
    # Look for clickable controls representing the real server-side "신청" state.
    # Avoid matching "신청예정" or "마감".
    xpaths: List[str] = [
        # Button or link explicitly labeled 신청
        "//a[not(contains(.,'예정')) and contains(normalize-space(.), '신청')]",
        "//button[not(contains(.,'예정')) and contains(normalize-space(.), '신청')]",
        "//input[( @type='button' or @type='submit') and contains(@value,'신청') and not(contains(@value,'예정'))]",
        # A status span saying '신청' with a clickable ancestor
        "//span[contains(@class,'status') and normalize-space(text())='신청']",
    ]
    for xp in xpaths:
        try:
            elems = driver.find_elements(By.XPATH, xp)
            for e in elems:
                if e.is_displayed():
                    # If it's already clickable control (a/button/input), return it
                    tag = e.tag_name.lower()
                    if tag in ("a", "button"):
                        return e
                    # climb ancestors to find nearest clickable anchor/button
                    anc = e
                    for _ in range(5):
                        anc = anc.find_element(By.XPATH, "..")
                        tag = anc.tag_name.lower()
                        if tag in ("a", "button"):
                            return anc
        except Exception:
            continue
    return None


def detect_captcha(driver) -> bool:
    # Heuristic detection of common CAPTCHA widgets
    try:
        # reCAPTCHA iframe or container
        if driver.find_elements(By.CSS_SELECTOR, 'iframe[src*="recaptcha"], .g-recaptcha, [id*="recaptcha" i], [class*="recaptcha" i]'):
            return True
        # Generic captcha keyword in inputs/images
        if driver.find_elements(By.XPATH, "//img[contains(translate(@src,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'captcha')] | //input[contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'captcha')]"):
            return True
    except Exception:
        pass
    return False


def is_rate_limited_message(msg: str) -> bool:
    if not msg:
        return False
    s = msg.lower()
    return any(k in s for k in ["too many", "429", "요청이 많", "과도한", "잠시 후", "rate limit"])  # heuristic


def verify_success_on_mypage(driver) -> bool:
    """Visit MyPage and look for evidence of the target application.
    Signals: query sn match, or table/link row containing sn, or user/child names.
    Writes HTML/PNG and a compact JSON summary.
    """
    import json as _json
    try:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(TARGET_URL)
        qs = parse_qs(parsed.query)
        sn = (qs.get('sn') or qs.get('SN') or [None])[0]
    except Exception:
        sn = None
    summary = {"sn": sn, "found": False, "matches": []}
    try:
        driver.get("https://www.sahascc.or.kr/mypage/Appchild.asp")
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
        page = driver.page_source
        # Heuristic: look for any anchor/link containing sn= or target title
        found = False
        if sn and (f"sn={sn}" in page):
            found = True
            summary["matches"].append({"type": "sn_in_html", "value": sn})

        # Try to parse basic table rows
        try:
            rows = driver.find_elements(By.XPATH, "//tr")
            for r in rows:
                txt = (r.text or "").strip()
                if not txt:
                    continue
                if sn and (str(sn) in txt):
                    summary["matches"].append({"type": "row_contains_sn", "value": txt[:120]})
                    found = True
                # match by names
                for key in ("name", "child_name"):
                    val = (USER_DATA.get(key) or "").strip()
                    if val and val in txt:
                        summary["matches"].append({"type": f"row_contains_{key}", "value": txt[:120]})
                        found = True
        except Exception:
            pass

        summary["found"] = bool(found)
        # Save artifacts
        os.makedirs("logs", exist_ok=True)
        try:
            driver.save_screenshot("logs/verify_mypage.png")
        except Exception:
            pass
        try:
            with open("logs/verify_mypage.html", "w", encoding="utf-8") as f:
                f.write(page)
        except Exception:
            pass
        try:
            with open("logs/verify_summary.json", "w", encoding="utf-8") as f:
                _json.dump(summary, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        evt(f"[verify] MyPage check: sn={sn}, found={found}")
        return found
    except Exception as e:
        evt(f"[verify] MyPage check error: {e}")
        return False


def try_direct_apply(driver) -> bool:
    """Try known apply flags on the same view page to expose the form quickly."""
    candidates = [
        _append_query(TARGET_URL, "apply=1"),
        _append_query(TARGET_URL, "mode=apply"),
    ]
    # Also try child regist page if we can extract sn
    import urllib.parse as _up
    try:
        parsed = _up.urlparse(TARGET_URL)
        qs = _up.parse_qs(parsed.query)
        sn = (qs.get('sn') or qs.get('SN') or [None])[0]
        if sn:
            candidates.insert(0, f"{parsed.scheme}://{parsed.netloc}/parent/Appchild_regist.asp?sn={sn}")
    except Exception:
        pass
    for url in candidates:
        try:
            driver.get(url)
            msg = wait_alert_and_accept(driver, timeout=2)
            if msg:
                print(f"[apply-flag] alert: {msg}")
            maybe_switch_iframe(driver)
            forms = driver.find_elements(By.TAG_NAME, "form")
            if forms:
                evt(f"[apply-flag] form detected via {url}")
                heuristic_fill_form(driver, forms[0], USER_DATA)
                agree_all(driver)
                submitted = submit_current_form(driver)
                if submitted:
                    evt("[apply-flag] submitted via flagged URL")
                return submitted
        except Exception as e:
            evt(f"[apply-flag] error with {url}: {e}")
    return False


def dump_performance_logs(driver, label_prefix: str = "perf") -> Optional[str]:
    os.makedirs("logs", exist_ok=True)
    ts = int(time.time())
    out_path = os.path.join("logs", f"{label_prefix}_{ts}.jsonl")
    try:
        entries = driver.get_log("performance")
    except Exception:
        entries = []
    if not entries:
        return None
    try:
        import json as _json
        with open(out_path, "w", encoding="utf-8") as f:
            for e in entries:
                # Each e is a dict with 'message' JSON string from CDP
                try:
                    msg = _json.loads(e.get("message", "{}"))
                except Exception:
                    msg = {"raw": e.get("message")}
                _json.dump(msg, f, ensure_ascii=False)
                f.write("\n")
        return out_path
    except Exception:
        return None


def safe_click(driver, elem) -> None:
    for _ in range(3):
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
            time.sleep(0.1)
            elem.click()
            return
        except (ElementClickInterceptedException, StaleElementReferenceException):
            time.sleep(0.2)


def switch_to_new_window_if_any(driver, prev_handles: List[str], timeout=3) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            handles = driver.window_handles
        except Exception:
            # Driver may have crashed or disconnected; skip switching gracefully
            print("[driver] Lost connection while checking window handles; skipping switch")
            return
        if len(handles) > len(prev_handles):
            new_handles = [h for h in handles if h not in prev_handles]
            if new_handles:
                try:
                    driver.switch_to.window(new_handles[-1])
                except Exception:
                    print("[driver] Unable to switch to new window; continuing")
                return
        time.sleep(0.1)


def maybe_switch_iframe(driver) -> None:
    # If a visible iframe contains a form or a confirmation, switch into it.
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
    except Exception:
        return
    for frame in iframes:
        try:
            if frame.is_displayed():
                driver.switch_to.frame(frame)
                # If a form is present, assume this is the right context.
                forms = driver.find_elements(By.TAG_NAME, "form")
                if forms:
                    return
                # Otherwise, pop back out and continue
                driver.switch_to.default_content()
        except Exception:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass


def agree_all(driver) -> None:
    # Prefer master checkbox if present
    try:
        chkall = driver.find_elements(By.CSS_SELECTOR, "#chkall, input[name='chkall']")
        for c in chkall:
            if c.is_displayed():
                try:
                    if not c.is_selected():
                        c.click()
                        evt("[agree] Clicked chkall")
                except Exception:
                    pass
                break
    except Exception:
        pass
    # Ensure agree radios are set to Y
    try:
        for name in ("agree1", "agree2", "agree3"):
            radios = driver.find_elements(By.XPATH, f"//input[@type='radio' and @name='{name}']")
            # Prefer option with value 'Y'
            target = None
            for r in radios:
                val = (r.get_attribute("value") or "").upper()
                if val == 'Y':
                    target = r
                    break
            if target and not target.is_selected():
                try:
                    target.click()
                except Exception:
                    pass
        evt("[agree] Ensured agree1/2/3 = Y")
    except Exception:
        pass


def fill_text(elem, value: str) -> None:
    try:
        if elem.get_attribute("readonly") or elem.get_attribute("disabled"):
            return
        elem.clear()
        if value:
            elem.send_keys(value)
    except Exception:
        pass


def label_text_for(driver, elem) -> str:
    try:
        eid = elem.get_attribute("id")
        if eid:
            lbl = driver.find_elements(By.XPATH, f"//label[@for='{eid}']")
            if lbl:
                return lbl[0].text.strip()
    except Exception:
        pass
    try:
        # Try closest preceding label within same container
        lbl = elem.find_element(By.XPATH, "ancestor-or-self::*[1]/preceding::label[1]")
        return lbl.text.strip()
    except Exception:
        return ""


def heuristic_fill_form(driver, form, user_data: dict) -> None:
    inputs = form.find_elements(By.XPATH, ".//input | .//select | .//textarea")
    for el in inputs:
        tag = el.tag_name.lower()
        itype = (el.get_attribute("type") or "").lower()
        name = (el.get_attribute("name") or "").lower()
        pid = (el.get_attribute("id") or "").lower()
        placeholder = (el.get_attribute("placeholder") or "").lower()
        label = label_text_for(driver, el).lower()

        # Skip hidden inputs
        if itype in ("hidden",):
            continue

        # Checkboxes: auto-check anything that looks like agreement
        if itype == "checkbox":
            text_blob = " ".join([name, pid, placeholder, label])
            if any(k in text_blob for k in ["agree", "동의", "약관", "개인정보", "동의함", "chkall", "checkall", "all"]):
                try:
                    if not el.is_selected():
                        el.click()
                except Exception:
                    pass
            continue

        # Radios: prefer first or one matching child/parent options (leave as-is if already selected)
        if itype == "radio":
            try:
                if not el.is_selected():
                    desired = (user_data.get("child_gender", "") or "").strip()
                    text_blob = (name + pid + label).lower()
                    # Consent radios: prefer selecting (yes) by default
                    if "agree" in text_blob and not el.is_selected():
                        el.click()
                    if desired:
                        if desired in ["남", "남자", "m", "male"] and any(k in text_blob for k in ["남", "남자", "male", "m"]):
                            el.click()
                        elif desired in ["여", "여자", "f", "female"] and any(k in text_blob for k in ["여", "여자", "female", "f"]):
                            el.click()
                    # If still not selected and looks required, choose it
                    if not el.is_selected() and any(k in text_blob for k in ["필수", "required", "성별", "남", "여"]):
                        el.click()
            except Exception:
                pass
            continue

        # Selects: pick first non-empty option or one matching child name
        if tag == "select":
            try:
                options = el.find_elements(By.TAG_NAME, "option")
                # Prefer option containing child name
                target_text = user_data.get("child_name", "")
                chosen = None
                if target_text:
                    for opt in options:
                        if target_text in (opt.text or ""):
                            chosen = opt
                            break
                if not chosen:
                    for opt in options:
                        val = (opt.get_attribute("value") or "").strip()
                        if val:
                            chosen = opt
                            break
                if chosen:
                    chosen.click()
            except Exception:
                pass
            continue

        # Text-like inputs/textarea (primary mapping)
        if itype in ("text", "tel", "email") or tag == "textarea" or itype == "":
            text_blob = " ".join([name, pid, placeholder, label])
            value = ""
            # Child name
            if any(k in text_blob for k in ["자녀", "아동", "아이"]) and any(k in text_blob for k in ["이름", "성명", "name"]):
                value = user_data.get("child_name", "")
            # Parent name
            elif any(k in text_blob for k in ["보호자", "신청자", "이름", "성명"]) and "자녀" not in text_blob:
                value = user_data.get("name", "")
            # Age
            elif any(k in text_blob for k in ["나이", "개월", "연령", "age"]):
                value = user_data.get("child_age", "")
            # Phone
            elif any(k in text_blob for k in ["휴대", "연락처", "전화", "핸드폰", "tel", "phone"]):
                value = user_data.get("phone", "")
            # Email
            elif any(k in text_blob for k in ["email", "이메일"]):
                value = user_data.get("email", "")
            # Address
            elif any(k in text_blob for k in ["주소", "address"]):
                value = user_data.get("address", "")

            # Fallback: leave empty if we don't have confident mapping
            if value:
                fill_text(el, value)

    # Birth date split fields: try year/month/day
    birth = user_data.get("child_birth", "").replace("/", "-")
    if birth and len(birth) in (8, 10):
        if len(birth) == 8:
            y, m, d = birth[:4], birth[4:6], birth[6:8]
        else:
            y, m, d = birth.split("-")
        for yq in ["birth", "생년", "년", "year", "yy"]:
            for el in form.find_elements(By.XPATH, f".//input[contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), '{yq}')]"):
                fill_text(el, y)
        for mq in ["월", "month", "mm"]:
            for el in form.find_elements(By.XPATH, f".//input[contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), '{mq}')]"):
                fill_text(el, m)
        for dq in ["일", "day", "dd"]:
            for el in form.find_elements(By.XPATH, f".//input[contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), '{dq}')]"):
                fill_text(el, d)

    # Second pass: ensure required-like fields are not empty
    inputs2 = form.find_elements(By.XPATH, ".//input | .//textarea")
    for el in inputs2:
        try:
            if el.get_attribute("readonly") or el.get_attribute("disabled"):
                continue
            val = (el.get_attribute("value") or "").strip()
            itype = (el.get_attribute("type") or "").lower()
            name = (el.get_attribute("name") or "").lower()
            label = label_text_for(driver, el).lower()
            required = bool(el.get_attribute("required") or ("*" in label) or ("필수" in label))
            if not required:
                continue
            if val:
                continue
            # Fill with type-appropriate fallback
            if itype == "email":
                fill_text(el, user_data.get("email", "test@example.com"))
            elif itype in ("tel", "number"):
                fallback = re.sub(r"\D", "", user_data.get("phone", "01012345678"))
                if not fallback:
                    fallback = "01012345678"
                fill_text(el, fallback)
            else:  # text/textarea/unknown
                fb = user_data.get("name") or user_data.get("child_name") or "자동입력"
                fill_text(el, fb)
        except Exception:
            continue


def submit_current_form(driver, timeout=10) -> bool:
    # Prefer a visible form containing a submit-capable control
    forms = driver.find_elements(By.TAG_NAME, "form")
    for form in forms or []:
        # Try standard submit buttons
        buttons = form.find_elements(By.XPATH, ".//button | .//input[@type='submit'] | .//input[@type='button']")
        # Heuristics: prioritize labels commonly used for submission
        preferred = []
        for b in buttons:
            txt = (b.text or b.get_attribute("value") or "").strip()
            if any(k in txt for k in ["신청", "접수", "제출", "등록", "확인"]):
                preferred.append(b)
        target_buttons = preferred or buttons
        for b in target_buttons:
            try:
                safe_click(driver, b)
                wait_alert_and_accept(driver, timeout=3)
                return True
            except Exception:
                continue
    # If no form, try a global submit-like control on the page
    try:
        # Prefer explicit javascript checkIt() anchors (common on this site)
        anchors = driver.find_elements(By.XPATH, "//a[contains(@href,'checkIt') or contains(.,'신청하기')]")
        for a in anchors:
            if a.is_displayed():
                safe_click(driver, a)
                wait_alert_and_accept(driver, timeout=3)
                return True
        b = driver.find_element(By.XPATH, "//button[contains(.,'신청') or contains(.,'제출') or contains(.,'등록') or contains(.,'확인')]")
        safe_click(driver, b)
        wait_alert_and_accept(driver, timeout=3)
        return True
    except Exception:
        # Last resort: JS submit if a form exists in DOM
        try:
            driver.execute_script("(function(){try{ if(document.myform){document.myform.submit(); return;} var f=document.querySelector('form'); if(f){f.submit();}}catch(e){}})();")
            wait_alert_and_accept(driver, timeout=3)
            return True
        except Exception:
            return False


def is_disconnect_error(e: Exception) -> bool:
    s = str(e).lower()
    tokens = [
        "connection refused",
        "failed to establish",
        "chrome not reachable",
        "disconnected",
        "invalid session id",
        "cannot connect to chrome",
    ]
    return any(t in s for t in tokens)


def bot_session(headless: bool = True) -> None:
    driver = build_driver(headless=headless)
    try:
        evt("[session] Driver started")
        # Versions/capabilities
        try:
            caps = getattr(driver, 'capabilities', {}) or {}
            bname = caps.get('browserName')
            bver = caps.get('browserVersion') or caps.get('version')
            cinfo = caps.get('chrome') or {}
            cdver = None
            if isinstance(cinfo, dict):
                cdver = cinfo.get('chromedriverVersion')
            evt(f"[session] Browser {bname} {bver}")
            if cdver:
                evt(f"[session] ChromeDriver {cdver}")
            # Warn if major versions differ grossly
            try:
                if bver and cdver:
                    import re as _re
                    m1 = _re.match(r"(\d+)", str(bver))
                    m2 = _re.match(r"(\d+)", str(cdver))
                    if m1 and m2 and m1.group(1) != m2.group(1):
                        evt(f"[warn] Chrome/Driver major mismatch: {bver} vs {cdver}")
            except Exception:
                pass
        except Exception:
            pass

        ensure_login(driver, USERNAME, PASSWORD)

        # Navigate and optionally wait until the scheduled time
        driver.get(TARGET_URL)
        evt(f"[nav] {TARGET_URL}")
        inject_same_tab_policy(driver)

        start_at_dt: Optional[datetime] = None
        if START_AT:
            try:
                start_at_dt = datetime.fromisoformat(START_AT)
            except ValueError:
                evt(f"Invalid START_AT format: {START_AT}")
                raise

        if start_at_dt:
            pre_time = start_at_dt - timedelta(minutes=5)
            now = datetime.now()
            if now < pre_time:
                evt(f"[wait] Until pre-window {pre_time.isoformat()} (5m before start). Refresh every 10m.")
                wait_until_with_refresh(driver, pre_time, refresh_interval_sec=600, start_dt=start_at_dt)

        # Phase 2: aggressive watch/click loop from 5m before until 5m after start
        evt("[poll] Aggressive watch from 5m before start (5s cadence)")
        end_time = (start_at_dt + timedelta(minutes=5)) if start_at_dt else (datetime.now() + timedelta(minutes=30))
        last_refresh = 0.0
        last_flag_try = 0.0
        rate_backoff = 12
        while datetime.now() < end_time:
            # 5-second refresh cadence with jitter in pre-window
            if time.time() - last_refresh > (5.0 + random.uniform(-1.0, 1.0)):
                try:
                    driver.refresh()
                except Exception:
                    evt("[driver] Refresh failed (driver may be gone); retrying later")
                last_refresh = time.time()
                time.sleep(0.1)
                # Re-apply popup suppression after navigation
                try:
                    inject_same_tab_policy(driver)
                except Exception:
                    pass

            # Lightweight keepalive to detect silent disconnects early
            try:
                driver.execute_script("return 1")
            except Exception as e:
                if is_disconnect_error(e):
                    raise
                evt(f"[driver] Non-fatal script error: {e}")

            apply_el = find_apply_element(driver)
            if apply_el:
                evt("[state] '신청' detected — attempting to click")
                try:
                    pre_handles = driver.window_handles[:]
                except Exception:
                    evt("[driver] Could not read window handles before click; continuing without switch aid")
                    pre_handles = []
                safe_click(driver, apply_el)
                msg = wait_alert_and_accept(driver, timeout=1)
                if msg:
                    evt(f"[alert] {msg}")
                    if is_rate_limited_message(msg):
                        evt(f"[backoff] Rate-limited, sleeping {rate_backoff}s")
                        time.sleep(rate_backoff)
                        rate_backoff = min(rate_backoff * 2, 60)
                        continue
                switch_to_new_window_if_any(driver, pre_handles, timeout=2)
                maybe_switch_iframe(driver)
                # CAPTCHA detection
                if detect_captcha(driver):
                    evt("[captcha] Detected. Saving snapshot and backing off 30s")
                    try:
                        with open("logs/captcha_page.html", "w", encoding="utf-8") as f:
                            f.write(driver.page_source)
                    except Exception:
                        pass
                    try:
                        driver.save_screenshot("logs/captcha_page.png")
                    except Exception:
                        pass
                    time.sleep(30)
                    continue
                break

            # Once actual start time has passed, also probe direct apply flags every ~5s
            if start_at_dt and datetime.now() >= start_at_dt and (time.time() - last_flag_try > (5.0 + random.uniform(-1.0, 1.0))):
                last_flag_try = time.time()
                if try_direct_apply(driver):
                    break

            # very small backoff
            time.sleep(0.2)
        else:
            evt("[timeout] '신청' state did not appear in time")
            return

        # At this point, either a confirmation flow or a form is expected
        evt("[followup] Handling follow-up flow")

        # If redirected to a form page, fill heuristically
        for _ in range(3):
            try:
                forms = driver.find_elements(By.TAG_NAME, "form")
                if forms:
                    evt(f"[form] Found {len(forms)} form(s) — filling heuristically")
                    heuristic_fill_form(driver, forms[0], USER_DATA)
                    agree_all(driver)
                    break
                # Wait a moment for dynamic content
                WebDriverWait(driver, 2).until(EC.presence_of_element_located((By.XPATH, "//form | //a[contains(@href,'checkIt')]")))
            except Exception:
                pass
            time.sleep(0.5)

        # Try to submit
        submitted = submit_current_form(driver)
        if submitted:
            evt("[submit] Submission attempted — waiting for result")
            # Wait for an alert/redirect indicating success or failure
            msg = wait_alert_and_accept(driver, timeout=3)
            if msg:
                evt(f"[result] {msg}")
                if is_rate_limited_message(msg):
                    evt("[backoff] Rate-limited on submit, sleeping 12s")
                    time.sleep(12)
            # Verify on MyPage
            verify_success_on_mypage(driver)
            # Give time for redirect if any
            time.sleep(1)
        else:
            evt("[submit] Could not find a submit control — trying direct apply flags.")
            if try_direct_apply(driver):
                evt("[submit] Completed via apply flags.")
                verify_success_on_mypage(driver)
            else:
                evt("[submit] No form via flags — manual review may be needed.")

        # Persist the final page for auditing
        try:
            with open("submission_result.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            evt("[save] Wrote submission_result.html")
        except Exception:
            pass

        # Dump performance logs for postmortem (HAR-like)
        try:
            perf_file = dump_performance_logs(driver, label_prefix="har")
            if perf_file:
                evt(f"[har] Wrote {perf_file}")
            else:
                evt("[har] No performance logs available")
        except Exception:
            pass

    finally:
        try:
            driver.quit()
        except Exception:
            pass



def main():
    import argparse
    global START_AT, TARGET_URL
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-headless", action="store_true", help="Run browser with UI visible")
    parser.add_argument("--start-at", default=None, help="Start time ISO (KST)")
    parser.add_argument("--target-url", default=None, help="Override target URL")
    parser.add_argument("--max-restarts", type=int, default=2, help="Max driver restarts on disconnect")
    args = parser.parse_args()

    if args.start_at:
        START_AT = args.start_at
    if args.target_url:
        TARGET_URL = args.target_url

    _init_event_log()
    headless = not args.no_headless

    max_restarts = max(0, int(args.max_restarts))
    for attempt in range(max_restarts + 1):
        try:
            bot_session(headless=headless)
            break
        except WebDriverException as e:
            if is_disconnect_error(e) and attempt < max_restarts:
                evt(f"[recover] Driver disconnected: {e}. Restarting session ({attempt+1}/{max_restarts})")
                time.sleep(1)
                continue
            raise
        except Exception as e:
            if is_disconnect_error(e) and attempt < max_restarts:
                evt(f"[recover] Connection issue: {e}. Restarting session ({attempt+1}/{max_restarts})")
                time.sleep(1)
                continue
            raise


if __name__ == "__main__":
    main()
