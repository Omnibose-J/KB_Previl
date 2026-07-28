#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import re
from pathlib import Path

# Read input
input_path = Path("batch1.json")
output_path = Path("out_b1_A.json")

with open(input_path, 'r', encoding='utf-8') as f:
    items = json.load(f)

# Classification rules
def classify_item(text):
    """
    Classify a blog excerpt for restaurant praise.
    Returns dict with taste, portion, value, mood, kind, fresh (bool), and quote (str).
    """
    result = {
        "taste": False,
        "portion": False,
        "value": False,
        "mood": False,
        "kind": False,
        "fresh": False,
        "quote": ""
    }

    # Lowercase for pattern matching (but preserve original for quotes)
    text_lower = text.lower()

    # List to track any praise found
    praises_found = []

    # 1. Taste (맛있다, 맛이 좋다, 맛있는, 등)
    taste_patterns = [
        r'맛있[다는었어요니다]',
        r'맛이\s*좋',
        r'맛\s*반',  # 맛에 반하다
        r'최고다',
        r'입맛',  # 이게 내 입맛
        r'맛\s*더[니라]',  # 맛이 더하다
        r'깛(있)?다',  # 깛있다
        r'역시.*내\s*입맛',
    ]

    taste_quotes = []
    for pattern in taste_patterns:
        matches = re.finditer(pattern, text_lower)
        for match in matches:
            # Extract surrounding context (25 chars max, try to get whole phrase)
            start = max(0, match.start() - 10)
            end = min(len(text), match.end() + 15)
            snippet = text[start:end].strip()
            taste_quotes.append(snippet)

    if taste_quotes:
        result["taste"] = True
        praises_found.append(("taste", taste_quotes[0]))

    # 2. Portion (양이 많다, 푸짐하다, 리필, 양이 넉넉)
    portion_patterns = [
        r'양이?\s*많',
        r'푸짐',
        r'넉넉',
        r'대량',
        r'무한.*리필',
        r'양.*초과',
    ]

    portion_quotes = []
    for pattern in portion_patterns:
        matches = re.finditer(pattern, text_lower)
        for match in matches:
            start = max(0, match.start() - 10)
            end = min(len(text), match.end() + 15)
            snippet = text[start:end].strip()
            portion_quotes.append(snippet)

    if portion_quotes:
        result["portion"] = True
        praises_found.append(("portion", portion_quotes[0]))

    # 3. Value (가성비, 가격 대비 만족, 가격이 저렴, 쌀, 저가)
    value_patterns = [
        r'가성비',
        r'가격.*만족',
        r'만족[^했다는].*가격',
        r'저렴',
        r'가격.*좋',
        r'가격.*저',
        r'쌀',
        r'저가',
        r'가격.*훌륭',
    ]

    value_quotes = []
    for pattern in value_patterns:
        matches = re.finditer(pattern, text_lower)
        for match in matches:
            start = max(0, match.start() - 10)
            end = min(len(text), match.end() + 15)
            snippet = text[start:end].strip()
            value_quotes.append(snippet)

    if value_quotes:
        result["value"] = True
        praises_found.append(("value", value_quotes[0]))

    # 4. Mood (분위기, 인테리어, 환하, 깔끔, 아담, 예쁜, 아늑)
    mood_patterns = [
        r'분위기.*좋',
        r'인테리어.*좋',
        r'인테리어.*깔끔',
        r'환하',
        r'깔끔[하함]',
        r'아담',
        r'예쁘',
        r'아늑',
        r'분위기.*어울',
        r'분위기.*한층',
        r'감성',
        r'정취',
    ]

    mood_quotes = []
    for pattern in mood_patterns:
        matches = re.finditer(pattern, text_lower)
        for match in matches:
            start = max(0, match.start() - 10)
            end = min(len(text), match.end() + 15)
            snippet = text[start:end].strip()
            mood_quotes.append(snippet)

    if mood_quotes:
        result["mood"] = True
        praises_found.append(("mood", mood_quotes[0]))

    # 5. Kind/Service (친절, 응대, 서비스, 정성, 배려, 세심)
    kind_patterns = [
        r'친절',
        r'응대.*좋',
        r'응대.*친',
        r'서비스.*좋',
        r'정성',
        r'배려',
        r'세심',
        r'인심',
        r'사장님.*센스',
    ]

    kind_quotes = []
    for pattern in kind_patterns:
        matches = re.finditer(pattern, text_lower)
        for match in matches:
            start = max(0, match.start() - 10)
            end = min(len(text), match.end() + 15)
            snippet = text[start:end].strip()
            kind_quotes.append(snippet)

    if kind_quotes:
        result["kind"] = True
        praises_found.append(("kind", kind_quotes[0]))

    # 6. Fresh (신선, 신선한, 신선함)
    fresh_patterns = [
        r'신선[하함다]',
        r'신선한',
        r'신선함',
    ]

    fresh_quotes = []
    for pattern in fresh_patterns:
        matches = re.finditer(pattern, text_lower)
        for match in matches:
            start = max(0, match.start() - 10)
            end = min(len(text), match.end() + 15)
            snippet = text[start:end].strip()
            fresh_quotes.append(snippet)

    if fresh_quotes:
        result["fresh"] = True
        praises_found.append(("fresh", fresh_quotes[0]))

    # Set quote - use the first praise found, capped at 25 chars
    if praises_found:
        quote_text = praises_found[0][1]
        # Clean up and cap at 25 chars
        quote_text = quote_text.replace('\n', ' ').replace('  ', ' ')
        if len(quote_text) > 25:
            quote_text = quote_text[:25]
        result["quote"] = quote_text

    return result

# Process all items
output_data = {}
count_total = 0
count_with_praise = 0

for item in items:
    item_id = str(item["id"])
    text = item["text"]

    classification = classify_item(text)
    output_data[item_id] = {
        "taste": classification["taste"],
        "portion": classification["portion"],
        "value": classification["value"],
        "mood": classification["mood"],
        "kind": classification["kind"],
        "fresh": classification["fresh"],
        "quote": classification["quote"]
    }

    count_total += 1
    if any([classification["taste"], classification["portion"], classification["value"],
            classification["mood"], classification["kind"], classification["fresh"]]):
        count_with_praise += 1

# Write output
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(output_data, f, ensure_ascii=False, indent=0)

print(f"{count_total} {count_with_praise}")
