#!/usr/bin/env python3
"""
Batch fetch football match results from zgzcw.com using Playwright.
Strategy: Visit fenxi.zgzcw.com main page first for WAF cookie, then sequential requests with delays.
"""

import json
import os
import re
import time
import random
import sys

from playwright.sync_api import sync_playwright

# ============ Config ============
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE = os.path.join(BASE_DIR, "data", "unmatched_matches.json")
RESULTS_FILE = os.path.join(BASE_DIR, "data", "match_results.json")
FETCHED_FILE = os.path.join(BASE_DIR, "data", "fetched_scores.json")
BASE_URL = "http://fenxi.zgzcw.com"
DELAY_MIN = 2.0
DELAY_MAX = 3.5

# ============ Load Data ============
with open(INPUT_FILE) as f:
    unmatched = json.load(f)
with open(RESULTS_FILE) as f:
    results = json.load(f)
try:
    with open(FETCHED_FILE) as f:
        fetched = json.load(f)
except FileNotFoundError:
    fetched = {}

# Build existing results key set for dedup
existing_keys = set()
for r in results:
    key = (r['date'], r['home'], r['away'])
    existing_keys.add(key)

# Determine which matches need fetching
need_fetch = []
already_have = 0
for m in unmatched:
    mid = m['matchid']
    parts = m['match_name'].split(' vs ')
    home, away = parts[0].strip(), parts[1].strip()
    mt = m['match_time']
    month, day = mt.split(' ')[0].split('-')
    date_str = f"2026{month}{day}"
    key = (date_str, home, away)
    
    # Check if already in results
    if key in existing_keys:
        already_have += 1
        continue
    
    # Check if already successfully fetched
    if mid in fetched and 'score_h' in fetched[mid] and 'error' not in fetched[mid]:
        already_have += 1
        continue
    
    need_fetch.append(m)

print(f"Already have results: {already_have}")
print(f"Need to fetch: {len(need_fetch)}")

if not need_fetch:
    print("Nothing to fetch!")
    sys.exit(0)

# ============ First, add previously fetched scores to results ============
new_from_cache = 0
for m in unmatched:
    mid = m['matchid']
    if mid not in fetched:
        continue
    info = fetched[mid]
    if 'error' in info or 'score_h' not in info:
        continue
    
    parts = m['match_name'].split(' vs ')
    home, away = parts[0].strip(), parts[1].strip()
    mt = m['match_time']
    month, day = mt.split(' ')[0].split('-')
    date_str = f"2026{month}{day}"
    key = (date_str, home, away)
    
    if key not in existing_keys:
        results.append({
            "date": date_str,
            "home": home,
            "away": away,
            "score_h": info['score_h'],
            "score_a": info['score_a']
        })
        existing_keys.add(key)
        new_from_cache += 1

print(f"Added {new_from_cache} results from previous fetch cache")

# ============ Playwright Fetch ============
def extract_score_from_element(text):
    """Extract score from vs-score element text like '2 - 3\n\n(半场：2-2)'"""
    m = re.search(r'(\d+)\s*-\s*(\d+)', text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def is_blocked_page(content):
    """Check if the page is blocked by WAF."""
    return 'The access is blocked' in content or len(content) < 5000


success_count = 0
fail_count = 0
blocked_count = 0
new_results = []
retry_queue = []

print(f"\nStarting Playwright fetch for {len(need_fetch)} matches...")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    
    # Step 1: Visit fenxi main page to get WAF cookie
    print("Visiting fenxi.zgzcw.com for WAF cookie...")
    page.goto("http://fenxi.zgzcw.com/", timeout=30000, wait_until="domcontentloaded")
    time.sleep(5)
    print(f"Main page loaded, title: {page.title()}")
    
    # Step 2: Sequential fetch each match
    for i, match in enumerate(need_fetch):
        mid = match['matchid']
        name = match['match_name']
        url = f"{BASE_URL}/{mid}/bjop"
        
        score_found = False
        
        try:
            page.goto(url, timeout=20000, wait_until="domcontentloaded")
            time.sleep(2)
            
            content = page.content()
            
            # Check if blocked
            if is_blocked_page(content):
                print(f"[{i+1}/{len(need_fetch)}] {name} - BLOCKED, will retry")
                retry_queue.append(match)
                blocked_count += 1
            else:
                # Try to extract score from vs-score element
                vs_score_el = page.query_selector('.vs-score')
                if vs_score_el:
                    text = vs_score_el.inner_text()
                    scores = extract_score_from_element(text)
                    if scores:
                        score_h, score_a = scores
                        print(f"[{i+1}/{len(need_fetch)}] {name} - Score: {score_h}-{score_a}")
                        
                        parts = name.split(' vs ')
                        home, away = parts[0].strip(), parts[1].strip()
                        mt = match['match_time']
                        month, day = mt.split(' ')[0].split('-')
                        date_str = f"2026{month}{day}"
                        
                        result_entry = {
                            "date": date_str,
                            "home": home,
                            "away": away,
                            "score_h": score_h,
                            "score_a": score_a
                        }
                        
                        key = (date_str, home, away)
                        if key not in existing_keys:
                            new_results.append(result_entry)
                            existing_keys.add(key)
                        
                        fetched[mid] = {
                            "score_h": score_h,
                            "score_a": score_a,
                            "score_text": f"{score_h}-{score_a}"
                        }
                        
                        success_count += 1
                        score_found = True
                    else:
                        print(f"[{i+1}/{len(need_fetch)}] {name} - No score in vs-score: {text[:50]}")
                        fetched[mid] = {"error": "no_score_parse", "text": text[:100]}
                        fail_count += 1
                else:
                    # No vs-score element - match might not have result yet
                    print(f"[{i+1}/{len(need_fetch)}] {name} - No vs-score element (content_len={len(content)})")
                    fetched[mid] = {"error": "no_vs_score", "content_len": len(content)}
                    fail_count += 1
        
        except Exception as e:
            print(f"[{i+1}/{len(need_fetch)}] {name} - Error: {e}")
            fetched[mid] = {"error": str(e)}
            fail_count += 1
        
        # Delay between requests
        if i < len(need_fetch) - 1:
            delay = random.uniform(DELAY_MIN, DELAY_MAX)
            time.sleep(delay)
    
    # Step 3: Retry blocked matches with longer delays
    if retry_queue:
        print(f"\n--- Retrying {len(retry_queue)} blocked matches ---")
        # Re-visit main page
        page.goto("http://fenxi.zgzcw.com/", timeout=30000, wait_until="domcontentloaded")
        time.sleep(8)
        
        for i, match in enumerate(retry_queue):
            mid = match['matchid']
            name = match['match_name']
            url = f"{BASE_URL}/{mid}/bjop"
            
            try:
                page.goto(url, timeout=20000, wait_until="domcontentloaded")
                time.sleep(4)  # Longer wait
                
                content = page.content()
                
                if is_blocked_page(content):
                    print(f"  RETRY [{i+1}/{len(retry_queue)}] {name} - STILL BLOCKED")
                    fetched[mid] = {"error": "blocked_retry", "content_len": len(content)}
                    continue
                
                vs_score_el = page.query_selector('.vs-score')
                if vs_score_el:
                    text = vs_score_el.inner_text()
                    scores = extract_score_from_element(text)
                    if scores:
                        score_h, score_a = scores
                        print(f"  RETRY [{i+1}/{len(retry_queue)}] {name} - Score: {score_h}-{score_a}")
                        
                        parts = name.split(' vs ')
                        home, away = parts[0].strip(), parts[1].strip()
                        mt = match['match_time']
                        month, day = mt.split(' ')[0].split('-')
                        date_str = f"2026{month}{day}"
                        
                        result_entry = {
                            "date": date_str,
                            "home": home,
                            "away": away,
                            "score_h": score_h,
                            "score_a": score_a
                        }
                        
                        key = (date_str, home, away)
                        if key not in existing_keys:
                            new_results.append(result_entry)
                            existing_keys.add(key)
                        
                        fetched[mid] = {
                            "score_h": score_h,
                            "score_a": score_a,
                            "score_text": f"{score_h}-{score_a}"
                        }
                        
                        success_count += 1
                        blocked_count -= 1
                        continue
                
                print(f"  RETRY [{i+1}/{len(retry_queue)}] {name} - No score found")
                fetched[mid] = {"error": "no_score_retry", "content_len": len(content)}
            
            except Exception as e:
                print(f"  RETRY [{i+1}/{len(retry_queue)}] {name} - Error: {e}")
                fetched[mid] = {"error": f"retry_error: {e}"}
            
            time.sleep(random.uniform(3, 5))
    
    browser.close()

# ============ Save Results ============
results.extend(new_results)

with open(RESULTS_FILE, 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

with open(FETCHED_FILE, 'w') as f:
    json.dump(fetched, f, ensure_ascii=False, indent=2)

# ============ Summary ============
print(f"\n{'='*50}")
print(f"SUMMARY")
print(f"{'='*50}")
print(f"Total needed fetch: {len(need_fetch)}")
print(f"Successfully fetched: {success_count}")
print(f"Failed (no score): {fail_count}")
print(f"Blocked by WAF: {blocked_count}")
print(f"Added from cache: {new_from_cache}")
print(f"New results added: {len(new_results) + new_from_cache}")
print(f"Total results in file: {len(results)}")
