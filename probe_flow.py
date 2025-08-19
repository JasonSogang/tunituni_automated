import os
import json
import time
import shutil
from datetime import datetime
from typing import Dict, Any, List

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


LOGIN_URL = "https://www.sahascc.or.kr/member/login.asp"
TARGET_URL = "https://www.sahascc.or.kr/parent/Appchild_view.asp?sn=108"  # edit if needed
USERNAME = "kfqsangwoo"      # edit
PASSWORD = "1wndeowkd1!"  # edit


def build_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    )
    # Enable console/performance logs when available
    opts.set_capability("goog:loggingPrefs", {"browser": "ALL", "performance": "ALL"})

    chromedriver_path = shutil.which("chromedriver") or "/usr/bin/chromedriver"
    if chromedriver_path and os.path.exists(chromedriver_path):
        service = Service(chromedriver_path)
        return webdriver.Chrome(service=service, options=opts)
    return webdriver.Chrome(options=opts)


def ensure_login(driver: webdriver.Chrome, username: str, password: str, timeout=20) -> None:
    if not username or not password:
        raise RuntimeError("USERNAME/PASSWORD not set in script")
    driver.get(LOGIN_URL)
    WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.NAME, "userid")))
    driver.find_element(By.NAME, "userid").clear()
    driver.find_element(By.NAME, "userid").send_keys(username)
    driver.find_element(By.NAME, "Pass").clear()
    driver.find_element(By.NAME, "Pass").send_keys(password)
    submits = driver.find_elements(By.XPATH, "//input[@type='submit']")
    (submits[1] if len(submits) >= 2 else submits[0]).click()
    # Accept any alert on login
    try:
        WebDriverWait(driver, 5).until(EC.alert_is_present())
        driver.switch_to.alert.accept()
    except Exception:
        pass
    WebDriverWait(driver, timeout).until(EC.url_changes(LOGIN_URL))


def find_apply_control(driver: webdriver.Chrome):
    # Focus: actionable controls, not status badges
    xps = [
        "//div[contains(@class,'btn-grp')]//a[contains(normalize-space(.), '신청')]",
        "//div[contains(@class,'btn-grp')]//button[contains(normalize-space(.), '신청')]",
        "//div[contains(@class,'btn-grp')]//input[( @type='button' or @type='submit') and contains(@value,'신청')]",
        # fallbacks
        "//a[contains(normalize-space(.), '신청') and not(contains(normalize-space(.),'예정'))]",
        "//button[contains(normalize-space(.), '신청') and not(contains(normalize-space(.),'예정'))]",
    ]
    for xp in xps:
        elems = driver.find_elements(By.XPATH, xp)
        for e in elems:
            if e.is_displayed():
                return e
    return None


def collect_console_logs(driver: webdriver.Chrome) -> List[Dict[str, Any]]:
    try:
        return driver.get_log("browser")
    except Exception:
        return []


def dump_artifacts(driver: webdriver.Chrome, base: str, meta: Dict[str, Any]):
    os.makedirs(os.path.dirname(base), exist_ok=True)
    # HTML
    try:
        with open(base + ".html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
    except Exception:
        pass
    # Screenshot
    try:
        driver.save_screenshot(base + ".png")
    except Exception:
        pass
    # Metadata
    try:
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def enumerate_forms(driver: webdriver.Chrome) -> List[Dict[str, Any]]:
    forms_meta: List[Dict[str, Any]] = []
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
        forms_meta.append(fm)
    return forms_meta


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_base = os.path.join("logs", f"probe_{ts}")
    driver = build_driver()
    try:
        ensure_login(driver, USERNAME, PASSWORD)
        driver.get(TARGET_URL)

        # Pre-click snapshot
        meta: Dict[str, Any] = {
            "stage": "pre_click",
            "url": driver.current_url,
            "console": collect_console_logs(driver),
            "forms": enumerate_forms(driver),
            "window_handles": driver.window_handles,
        }
        dump_artifacts(driver, out_base + "_pre", meta)

        # Wait briefly for a real '신청' control to appear
        # (Don’t mutate DOM; this is a non-invasive probe.)
        apply_el = None
        try:
            for _ in range(30):  # ~15s
                apply_el = find_apply_control(driver)
                if apply_el:
                    break
                time.sleep(0.5)
        except Exception:
            pass

        if not apply_el:
            print("[probe] No actionable '신청' control detected (still '신청예정'?)")
            return

        prev_handles = driver.window_handles[:]
        apply_el.click()

        # Post-click: capture alert if any
        alert_texts: List[str] = []
        try:
            WebDriverWait(driver, 2).until(EC.alert_is_present())
            alert = driver.switch_to.alert
            alert_texts.append(alert.text)
            alert.accept()
        except Exception:
            pass

        # Switch to new window if opened
        try:
            for _ in range(10):
                handles = driver.window_handles
                if len(handles) > len(prev_handles):
                    newh = [h for h in handles if h not in prev_handles][-1]
                    driver.switch_to.window(newh)
                    break
                time.sleep(0.2)
        except Exception:
            pass

        # Try switching into a visible iframe that contains a form
        try:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for frm in iframes:
                if frm.is_displayed():
                    driver.switch_to.frame(frm)
                    if driver.find_elements(By.TAG_NAME, "form"):
                        break
                    driver.switch_to.default_content()
        except Exception:
            pass

        # Post-click snapshot
        meta2: Dict[str, Any] = {
            "stage": "post_click",
            "url": driver.current_url,
            "alert_texts": alert_texts,
            "console": collect_console_logs(driver),
            "forms": enumerate_forms(driver),
            "window_handles": driver.window_handles,
        }
        dump_artifacts(driver, out_base + "_post", meta2)
        print(f"[probe] Artifacts saved under {out_base}_*.html/.png/.json")

    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
