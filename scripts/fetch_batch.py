#!/usr/bin/env python3
"""
Batch fetch football match results from zgzcw.com using Playwright.
Processes one batch file at a time, updates fetched_scores.json incrementally.
"""
import json, os, re, time, random, sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
RESULTS_FILE = os.path.join(DATA_DIR, "match_results.json")
FETCHED_FILE = os.path.join(DATA_DIR, "fetched_scores.json")
BASE_URL = "http://fenxi.zgzcw.com"
DELAY_MIN = 1.5
DELAY_MAX = 2.5

batch_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
batch_file = os.path.join(DATA_DIR, f"batch_{batch_idx}.json")

with open(batch_file) as f:
    batch_matches = json.load(f)
with open(RESULTS_FILE) as f:
    results = json.load(f)
with open(FETCHED_FILE) as f:
    fetched = json.load(f)

existing_keys = set((r['date'], r['home'], r['away']) for r in results)

def extract_score_from_element(text):
    m = re.search(r'(\d+)\s*-\s*(\d+)', text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None

def is_blocked(content):
    return 'The access is blocked' in content or len(content) < 5000

success_count = 0
fail_count = 0
new_results = []

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    
    # Visit main page for WAF cookie
    print(f"Batch {batch_idx}: Visiting fenxi.zgzcw.com...")
    page.goto("http://fenxi.zgzcw.com/", timeout=30000, wait_until="domcontentloaded")
    time.sleep(4)
    print(f"Main page title: {page.title()}")
    
    for i, match in enumerate(batch_matches):
        mid = match['matchid']
        name = match['match_name']
        url = f"{BASE_URL}/{mid}/bjop"
        
        try:
            page.goto(url, timeout=15000, wait_until="domcontentloaded")
            time.sleep(1.5)
            content = page.content()
            
            if is_blocked(content):
                # Retry once with longer wait
                time.sleep(3)
                page.goto(url, timeout=15000, wait_until="domcontentloaded")
                time.sleep(3)
                content = page.content()
            
            if is_blocked(content):
                print(f"[{i+1}/{len(batch_matches)}] {name} - BLOCKED")
                fetched[mid] = {"error": "blocked", "content_len": len(content)}
                fail_count += 1
            else:
                vs_score_el = page.query_selector('.vs-score')
                if vs_score_el:
                    text = vs_score_el.inner_text()
                    scores = extract_score_from_element(text)
                    if scores:
                        score_h, score_a = scores
                        print(f"[{i+1}/{len(batch_matches)}] {name} - {score_h}-{score_a}")
                        parts = name.split(' vs ')
                        home, away = parts[0].strip(), parts[1].strip()
                        mt = match['match_time']
                        month, day = mt.split(' ')[0].split('-')
                        date_str = f"2026{month}{day}"
                        key = (date_str, home, away)
                        if key not in existing_keys:
                            new_results.append({"date": date_str, "home": home, "away": away, "score_h": score_h, "score_a": score_a})
                            existing_keys.add(key)
                        fetched[mid] = {"score_h": score_h, "score_a": score_a, "score_text": f"{score_h}-{score_a}"}
                        success_count += 1
                    else:
                        print(f"[{i+1}/{len(batch_matches)}] {name} - no parse: {text[:40]}")
                        fetched[mid] = {"error": "no_score_parse", "text": text[:80]}
                        fail_count += 1
                else:
                    print(f"[{i+1}/{len(batch_matches)}] {name} - no vs-score (len={len(content)})")
                    fetched[mid] = {"error": "no_vs_score", "content_len": len(content)}
                    fail_count += 1
        except Exception as e:
            print(f"[{i+1}/{len(batch_matches)}] {name} - Error: {e}")
            fetched[mid] = {"error": str(e)}
            fail_count += 1
        
        if i < len(batch_matches) - 1:
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    
    browser.close()

# Save incrementally
results.extend(new_results)
with open(RESULTS_FILE, 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
with open(FETCHED_FILE, 'w') as f:
    json.dump(fetched, f, ensure_ascii=False, indent=2)

print(f"\nBatch {batch_idx} done: success={success_count}, fail={fail_count}, new={len(new_results)}")
