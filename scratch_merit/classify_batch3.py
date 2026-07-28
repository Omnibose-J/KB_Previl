import json
import re
from pathlib import Path

# Load input
with open('batch3.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

results = {}

# Define Korean praise patterns for each category
patterns = {
    'taste': [
        r'맛(?:이|있|없)',
        r'맛있',
        r'맛나',
        r'맛[을는]',
        r'아[주맛]내',
        r'맛집',
        r'(ㅋ*맛+)',
        r'[맛]있[게다]',
        r'소문대로 맛',
        r'정말.*맛',
        r'진짜.*맛',
        r'넘나 맛',
    ],
    'portion': [
        r'양.*많',
        r'량.*많',
        r'푸짐',
        r'양.*넉넉',
        r'(내용물|구성).*많',
        r'넉넉[하게]',
        r'많[은이]',
    ],
    'value': [
        r'가성비',
        r'저렴',
        r'싸',
        r'착한.*가격',
        r'가격.*만족',
        r'가격.*대비',
        r'착한',
        r'저렴[한]',
    ],
    'mood': [
        r'분위기.*좋',
        r'인테리어',
        r'분위기',
        r'[깔]끔',
        r'감성',
        r'따뜻[하게]',
        r'넓',
        r'[아소담]',
        r'깨끗',
        r'좋은 점은 넓',
    ],
    'kind': [
        r'친절',
        r'친절[하게]',
        r'응대.*좋',
        r'손님.*좋',
        r'사장님.*좋',
        r'주인.*좋',
        r'이모님.*좋',
        r'훈남사장',
        r'사장.*짱',
    ],
    'fresh': [
        r'신선',
        r'신선[한]',
        r'생고기',
        r'생물',
        r'신선[한].*해',
        r'신선[한].*회',
    ],
}

# Extract text before 25 chars for quote purposes
def extract_quote(text, pattern, category):
    """Extract a quote from text matching pattern for a category."""
    # Search for the pattern and surrounding context
    match = re.search(pattern, text)
    if match:
        start = max(0, match.start() - 10)
        end = min(len(text), match.end() + 15)
        quote = text[start:end].strip()
        # Trim to ~25 chars
        if len(quote) > 25:
            quote = quote[:25]
        return quote
    return ""

# Process each item
for item in data:
    item_id = str(item['id'])
    text = item['text']

    # Check if non-restaurant post
    is_non_restaurant = any([
        re.search(r'(부동산|전자담배|미용|살롱|일자리|구인|영화|폐기물|화분|공항)', text),
        re.search(r'(지하주차장|공사|세차|택시|호텔|호캉스)', text),
    ])

    if is_non_restaurant:
        results[item_id] = {
            'taste': False,
            'portion': False,
            'value': False,
            'mood': False,
            'kind': False,
            'fresh': False,
            'quote': ''
        }
        continue

    # Analyze for praise
    found_praise = {}
    quote_text = ""

    for category, pattern_list in patterns.items():
        found = False
        for pattern in pattern_list:
            if re.search(pattern, text, re.IGNORECASE):
                found = True
                # Try to extract quote
                if not quote_text:
                    quote_text = extract_quote(text, pattern, category)
                break
        found_praise[category] = found

    # If any praise found but no quote extracted, mark all false
    if any(found_praise.values()) and not quote_text:
        results[item_id] = {
            'taste': False,
            'portion': False,
            'value': False,
            'mood': False,
            'kind': False,
            'fresh': False,
            'quote': ''
        }
    else:
        results[item_id] = {
            'taste': found_praise['taste'],
            'portion': found_praise['portion'],
            'value': found_praise['value'],
            'mood': found_praise['mood'],
            'kind': found_praise['kind'],
            'fresh': found_praise['fresh'],
            'quote': quote_text if any(found_praise.values()) else ''
        }

# Write output
output_path = Path('out_b3_B.json')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

# Count results
total = len(results)
with_praise = sum(1 for r in results.values() if any([r['taste'], r['portion'], r['value'], r['mood'], r['kind'], r['fresh']]))

print(f"{total} {with_praise}")
