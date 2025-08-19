import os
import re
import json
import time
import shutil
from datetime import datetime
from typing import List, Dict, Any

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ====== USER CONFIG ======
BASE = "https://www.sahascc.or.kr"
LOGIN_URL = f"{BASE}/member/login.asp"
TARGET_SN = 108  # change if needed
USERNAME = "kfqsangwoo"
PASSWORD = "1wndeowkd1!"
# =========================


def build_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1400,900")
    chromedriver_path = shutil.which("chromedriver") or "/usr/bin/chromedriver"
    if chromedriver_path and os.path.exists(chromedriver_path):
        service = Service(chromedriver_path)
        return webdriver.Chrome(service=service, options=opts)
    return webdriver.Chrome(options=opts)


def selenium_login_get_session() -> requests.Session:
    driver = build_driver()
    try:
        driver.get(LOGIN_URL)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.NAME, "userid")))
        driver.find_element(By.NAME, "userid").clear()
        driver.find_element(By.NAME, "userid").send_keys(USERNAME)
        driver.find_element(By.NAME, "Pass").clear()
        driver.find_element(By.NAME, "Pass").send_keys(PASSWORD)
        submits = driver.find_elements(By.XPATH, "//input[@type='submit']")
        (submits[1] if len(submits) >= 2 else submits[0]).click()
        # Alert swallow
        try:
            WebDriverWait(driver, 3).until(EC.alert_is_present())
            driver.switch_to.alert.accept()
        except Exception:
            pass
        WebDriverWait(driver, 10).until(EC.url_changes(LOGIN_URL))

        sess = requests.Session()
        # Copy cookies
        for c in driver.get_cookies():
            sess.cookies.set(c['name'], c['value'], domain=c.get('domain'))
        return sess
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def candidate_paths(sn: int) -> List[str]:
    names = [
        "Appchild", "AppChild", "appchild",
        "ChildApply", "ApplyChild", "ChildApp", "ChildReg",
    ]
    suffixes = [
        "", "_write", "_apply", "_form", "_input", "_proc", "_ok", "_insert", "_reg", "_request", "_submit", "_join",
        "_regist", "_regist_ok",
        "Write", "Apply", "Form", "Input", "Proc", "Ok", "Insert", "Reg", "Request", "Submit", "Join",
        "Regist", "Regist_ok",
    ]
    folders = ["parent", "mypage"]
    out = []
    for f in folders:
        for n in names:
            for s in suffixes:
                out.append(f"/{f}/{n}{s}.asp?sn={sn}")
    # Also try without sn to see redirections
    for f in folders:
        for n in names:
            for s in suffixes:
                out.append(f"/{f}/{n}{s}.asp")
    # A few other likely generic handlers
    out += [
        f"/parent/Appchild_view.asp?sn={sn}&mode=apply",
        f"/parent/Appchild_view.asp?apply=1&sn={sn}",
        f"/parent/apply.asp?sn={sn}",
        f"/parent/apply_ok.asp?sn={sn}",
    ]
    # Deduplicate while preserving order
    seen = set()
    uniq = []
    for p in out:
        if p not in seen:
            uniq.append(p)
            seen.add(p)
    return uniq


def main():
    sess = selenium_login_get_session()
    paths = candidate_paths(TARGET_SN)
    results: List[Dict[str, Any]] = []
    os.makedirs("logs", exist_ok=True)
    ts = int(time.time())

    for i, path in enumerate(paths):
        url = BASE + path
        try:
            r = sess.get(url, allow_redirects=True, timeout=10)
            info: Dict[str, Any] = {
                "path": path,
                "status": r.status_code,
                "final_url": r.url,
                "len": len(r.text or ""),
                "has_form": ("<form" in (r.text or "").lower()),
            }
            # Heuristic: save interesting responses
            if r.status_code in (200, 302, 303) and (info["has_form"] or "신청" in r.text or "동의" in r.text):
                sample = f"logs/preflight_{ts}_{i}.html"
                with open(sample, "w", encoding="utf-8") as f:
                    f.write(r.text)
                info["saved"] = sample
            results.append(info)
        except Exception as e:
            results.append({"path": path, "error": str(e)})

    out = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "sn": TARGET_SN,
        "results": results,
    }
    out_file = f"logs/preflight_map_{ts}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[preflight] Wrote {out_file}. Interesting HTML (if any) saved as logs/preflight_*_*.html")


if __name__ == "__main__":
    main()
