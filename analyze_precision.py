#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
from pathlib import Path
from anthropic import Anthropic

# Initialize Anthropic client
client = Anthropic()

# Load batch data
input_path = Path(r"C:\Users\sobeo\Desktop\KB\scratch_precision\batch3.json")
output_path = Path(r"C:\Users\sobeo\Desktop\KB\scratch_precision\out_b3_A.json")

with open(input_path, 'r', encoding='utf-8') as f:
    batch_data = json.load(f)

# System prompt for Claude
system_prompt = """당신은 한국어 블로그 글을 분석하는 평가자입니다.

각 글에 대해 아래 항목들을 판정하세요:

1. visit: 이 글이 음식점 방문기인가? 미용실·부동산·구인·상품 리뷰·영화 등 음식점 방문과 무관하면 false
2. target: 글에 담긴 불만이 제시된 상호명 가게에 대한 것인가? 불만이 아예 없으면 null. 다른 가게·배달앱·주변 환경에 대한 불만이면 false
3. wait: 대기·웨이팅이 길다, 줄 서야 한다는 불만이 있는가
4. seat: 좌석이 좁다·불편하다·자리가 없다는 불만이 있는가
5. service: 응대가 불친절하다·느리다는 불만이 있는가
6. clean: 위생·청결이 나쁘다는 불만이 있는가
7. price: 가격이 비싸다·가격 대비 아쉽다는 불만이 있는가
8. noise: 시끄럽다·정신없다는 불만이 있는가
9. parking: 주차가 어렵다·주차장이 없다는 불만이 있는가

**규칙**:
- 칭찬은 불만이 아니다. "가성비 좋다"는 price false
- 본문에 근거 문장이 있어야 true다. 상호명·해시태그·제목의 단어만으로 추론하지 마라
- 사실 서술과 불만을 구분하라. "주차 가능하지만 협소함"은 parking true, "주차장 넓어요"는 false
- 애매하면 false

응답 형식: 한 글당 한 줄, id와 JSON을 탭으로 구분
예:
14492	{"visit": true, "target": true, "wait": false, "seat": false, "service": false, "clean": false, "price": false, "noise": false, "parking": false}
14561	{"visit": false, "target": null, "wait": false, "seat": false, "service": false, "clean": false, "price": false, "noise": false, "parking": false}
"""

# Process in batches of 15 articles
batch_size = 15
result = {}

total_batches = (len(batch_data) + batch_size - 1) // batch_size
print(f"Processing {len(batch_data)} articles in {total_batches} batches (size: {batch_size})...")

try:
    for batch_idx in range(0, len(batch_data), batch_size):
        batch_articles = batch_data[batch_idx:batch_idx + batch_size]
        batch_num = batch_idx // batch_size + 1

        # Prepare batch text
        batch_text = ""
        for article in batch_articles:
            batch_text += f"ID: {article['id']}\n상호명: {article['상호명']}\n본문: {article['본문']}\n\n"

        user_message = f"""아래 {len(batch_articles)}개의 블로그 글을 분석해주세요:

{batch_text}

각 글을 위의 규칙에 따라 판정하고, 응답 형식대로 ID와 JSON을 탭으로 구분하여 출력해주세요."""

        # Call Claude API
        response = client.messages.create(
            model="claude-opus-4-1-20250805",
            max_tokens=5000,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": user_message
            }]
        )

        # Extract response
        response_text = response.content[0].text

        # Parse response lines
        lines = response_text.strip().split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Try to split by tab
            parts = line.split('\t')
            if len(parts) == 2:
                article_id = parts[0].strip()
                json_str = parts[1].strip()
                try:
                    judgment = json.loads(json_str)
                    result[article_id] = judgment
                except json.JSONDecodeError:
                    pass
            else:
                # Try to extract ID and JSON pattern
                match = re.match(r'(\d+)\s+(\{.*\})', line)
                if match:
                    article_id = match.group(1)
                    json_str = match.group(2)
                    try:
                        judgment = json.loads(json_str)
                        result[article_id] = judgment
                    except json.JSONDecodeError:
                        pass

        print(f"  Batch {batch_num}/{total_batches} completed ({len(result)}/{len(batch_data)} total)")

    print(f"\nParsed {len(result)} articles from response")

    # Check if all articles are processed
    expected_ids = set(str(article['id']) for article in batch_data)
    parsed_ids = set(result.keys())

    if parsed_ids != expected_ids:
        missing = expected_ids - parsed_ids
        print(f"Warning: Missing {len(missing)} article(s)")
        if len(missing) <= 20:
            print(f"Missing IDs: {sorted(missing)}")

    # Fill in missing articles with default values
    for article in batch_data:
        article_id = str(article['id'])
        if article_id not in result:
            result[article_id] = {
                "visit": False,
                "target": None,
                "wait": False,
                "seat": False,
                "service": False,
                "clean": False,
                "price": False,
                "noise": False,
                "parking": False
            }

    # Save result
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=0)

    print(f"Results saved to: {output_path}")
    print(f"Total articles processed: {len(result)}/{len(batch_data)}")

except Exception as e:
    print(f"Error: {e}")
    raise
