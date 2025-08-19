import os
import time
import shutil
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


BASE = "https://www.sahascc.or.kr"
LOGIN_URL = f"{BASE}/member/login.asp"

# Hardcoded account
USERNAME = "kfqsangwoo"
PASSWORD = "1wndeowkd1!"

# Candidate listing pages to scan for an 'open' item
LISTING_URLS = [
    f"{BASE}/parent/Appchild.asp",               # 부모-자녀참여 프로그램
    f"{BASE}/parent/AppParent.asp",              # 부모교육
    f"{BASE}/guide/appPlayroom.asp",             # 놀이실(개인)
    f"{BASE}/guide/appPlayroom2.asp",            # 놀이실(기관)
    f"{BASE}/guide/appCulture.asp?Play_area=A",  # 공연/행사(개인)
    f"{BASE}/guide/appCulture.asp?Play_area=B",  # 공연/행사(기관)
    f"{BASE}/rainbow/AppRainbow.asp?Play_area=A&Code=1",
    f"{BASE}/rainbow/AppRainbow.asp?Play_area=A&Code=2",
    f"{BASE}/rainbow/AppRainbow.asp?Play_area=A&Code=3",
    f"{BASE}/parent/time_list.asp",              # 시간제보육
]


def build_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    )
    # Perf logs for HAR-like capture
    try:
        opts.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
    except Exception:
        pass
    chromedriver_path = shutil.which("chromedriver") or "/usr/bin/chromedriver"
    if chromedriver_path and os.path.exists(chromedriver_path):
        service = Service(chromedriver_path)
        return webdriver.Chrome(service=service, options=opts)
    return webdriver.Chrome(options=opts)


def wait_alert_and_accept(driver, timeout=2) -> Optional[str]:
    try:
        WebDriverWait(driver, timeout).until(EC.alert_is_present())
        a = driver.switch_to.alert
        txt = a.text
        a.accept()
        return txt
    except Exception:
        return None


def ensure_login(driver, timeout=20) -> None:
    driver.get(LOGIN_URL)
    WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.NAME, "userid")))
    driver.find_element(By.NAME, "userid").clear()
    driver.find_element(By.NAME, "userid").send_keys(USERNAME)
    driver.find_element(By.NAME, "Pass").clear()
    driver.find_element(By.NAME, "Pass").send_keys(PASSWORD)
    submits = driver.find_elements(By.XPATH, "//input[@type='submit']")
    (submits[1] if len(submits) >= 2 else submits[0]).click()
    wait_alert_and_accept(driver, timeout=5)
    WebDriverWait(driver, timeout).until(EC.url_changes(LOGIN_URL))


def enumerate_forms(driver) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    forms = driver.find_elements(By.TAG_NAME, "form")
    for idx, form in enumerate(forms):
        fm: Dict[str, Any] = {
            "index": idx,
            "action": form.get_attribute("action"),
            "method": form.get_attribute("method"),
            "inputs": [],
            "buttons": [],
        }
        inputs = form.find_elements(By.XPATH, ".//input | .//select | .//textarea")
        for inp in inputs:
            fm["inputs"].append({
                "tag": inp.tag_name,
                "type": inp.get_attribute("type"),
                "name": inp.get_attribute("name"),
                "id": inp.get_attribute("id"),
                "placeholder": inp.get_attribute("placeholder"),
                "required": bool(inp.get_attribute("required")),
            })
        buttons = form.find_elements(By.XPATH, ".//button | .//input[@type='submit'] | .//input[@type='button']")
        for b in buttons:
            fm["buttons"].append({
                "tag": b.tag_name,
                "type": b.get_attribute("type"),
                "name": b.get_attribute("name"),
                "text": b.text or b.get_attribute("value"),
            })
        out.append(fm)
    return out


def dump_perf(driver, prefix: str) -> Optional[str]:
    os.makedirs("logs", exist_ok=True)
    ts = int(time.time())
    path = f"logs/{prefix}_{ts}.jsonl"
    try:
        entries = driver.get_log("performance")
    except Exception:
        entries = []
    if not entries:
        return None
    try:
        with open(path, "w", encoding="utf-8") as f:
            for e in entries:
                try:
                    msg = json.loads(e.get("message", "{}"))
                except Exception:
                    msg = {"raw": e.get("message")}
                json.dump(msg, f, ensure_ascii=False)
                f.write("\n")
        return path
    except Exception:
        return None


def scan_and_probe(driver) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "found": False,
        "listing_url": None,
        "apply_html": None,
        "apply_href": None,
        "apply_onclick": None,
        "alerts": [],
        "after_url": None,
        "forms": [],
        "artifacts": {},
    }
    def try_capture_from_current(summary: Dict[str, Any]) -> bool:
        # Try direct '신청' controls on the current page (listing or detail)
        xps = [
            # Strict inside btn-grp
            "//div[contains(@class,'btn-grp')]//a[normalize-space(.)='신청']",
            "//div[contains(@class,'btn-grp')]//button[normalize-space(.)='신청']",
            "//div[contains(@class,'btn-grp')]//input[( @type='button' or @type='submit') and contains(@value,'신청')]",
            # Broader variants anywhere
            "//a[contains(normalize-space(.), '신청하기') or normalize-space(.)='신청' or contains(normalize-space(.),'예약') or contains(normalize-space(.),'접수')]",
            "//button[contains(normalize-space(.), '신청하기') or normalize-space(.)='신청' or contains(normalize-space(.),'예약') or contains(normalize-space(.),'접수')]",
            "//input[( @type='button' or @type='submit') and (contains(@value,'신청') or contains(@value,'예약') or contains(@value,'접수'))]",
        ]
        controls = []
        for xp in xps:
            controls.extend(driver.find_elements(By.XPATH, xp))
        controls = [c for c in controls if c.is_displayed()]
        if not controls:
            return False

        ctl = controls[0]
        summary["found"] = True
        summary["apply_html"] = ctl.get_attribute("outerHTML")
        summary["apply_href"] = ctl.get_attribute("href")
        summary["apply_onclick"] = ctl.get_attribute("onclick")

        pre_handles = driver.window_handles[:]
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", ctl)
        except Exception:
            pass
        ctl.click()

        msg = wait_alert_and_accept(driver, timeout=2)
        if msg:
            summary["alerts"].append(msg)

        # If a new window opened, switch
        end = time.time() + 3
        while time.time() < end:
            handles = driver.window_handles
            if len(handles) > len(pre_handles):
                newh = [h for h in handles if h not in pre_handles][-1]
                driver.switch_to.window(newh)
                break
            time.sleep(0.1)

        # Attempt iframe switch
        try:
            for fr in driver.find_elements(By.TAG_NAME, "iframe"):
                if fr.is_displayed():
                    driver.switch_to.frame(fr)
                    if driver.find_elements(By.TAG_NAME, "form"):
                        break
                    driver.switch_to.default_content()
        except Exception:
            pass

        summary["after_url"] = driver.current_url
        summary["forms"] = enumerate_forms(driver)

        # Save artifacts
        os.makedirs("logs", exist_ok=True)
        base = f"logs/open_scan_{int(time.time())}"
        try:
            driver.save_screenshot(base + ".png")
            summary["artifacts"]["screenshot"] = base + ".png"
        except Exception:
            pass
        try:
            with open(base + ".html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            summary["artifacts"]["html"] = base + ".html"
        except Exception:
            pass
        p = dump_perf(driver, prefix="open_scan_har")
        if p:
            summary["artifacts"]["har"] = p
        return True

    def collect_detail_links(max_links: int = 60) -> List[str]:
        hrefs = set()
        # Common view patterns across sections
        patterns = [
            "Appchild_view.asp",
            "AppParent_view.asp",
            "AppRainbow_view.asp",
            "view.asp",
        ]
        # try to scroll a bit to load lazy content
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2)")
            time.sleep(0.2)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.2)
            driver.execute_script("window.scrollTo(0, 0)")
        except Exception:
            pass

        anchors = driver.find_elements(By.XPATH, "//a[@href]")
        for a in anchors:
            h = a.get_attribute("href") or ""
            if not h.startswith(BASE):
                # make absolute if relative
                if h.startswith("/"):
                    h = BASE + h
            if BASE not in h:
                continue
            if any(p in h for p in patterns) and ("sn=" in h or "SN=" in h or "id=" in h.lower()):
                hrefs.add(h)
            if len(hrefs) >= max_links:
                break
        return list(hrefs)

    attempted_details: List[str] = []
    for url in LISTING_URLS:
        driver.get(url)
        time.sleep(0.5)
        # First try direct control on listing page
        summary["listing_url"] = url
        if try_capture_from_current(summary):
            break

        # If not found, navigate into detail pages we can discover
        detail_links = collect_detail_links(max_links=30)
        for href in detail_links:
            driver.get(href)
            attempted_details.append(href)
            time.sleep(0.3)
            if try_capture_from_current(summary):
                break
        if summary["found"]:
            break
    summary["attempted_details"] = attempted_details
    summary["tried_detail_count"] = len(attempted_details)
    return summary


def main():
    driver = build_driver()
    try:
        ensure_login(driver)
        result = scan_and_probe(driver)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
