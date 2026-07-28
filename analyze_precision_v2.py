#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
from pathlib import Path

# Load batch data
input_path = Path(r"C:\Users\sobeo\Desktop\KB\scratch_precision\batch3.json")
output_path = Path(r"C:\Users\sobeo\Desktop\KB\scratch_precision\out_b3_A.json")

with open(input_path, 'r', encoding='utf-8') as f:
    batch_data = json.load(f)

# Keywords for each category
keywords = {
    'wait': ['웨이팅', '대기', '줄', '기다리', '대기', '길다', '있었다', '기다'],
    'seat': ['좁', '자리', '좌석', '자리가', '협소', '밀집', '붙어', '답다'],
    'service': ['불친절', '느리', '응대', '친절', '서비스', '시간', '늦', '점원'],
    'clean': ['위생', '청결', '깨끗', '더럽', '비릿내', '냄새', '이물질', '거슬'],
    'price': ['비싸', '가격', '비용', '비', '후덜덜', '인상', '올', '가파'],
    'noise': ['시끄럽', '정신없', '시끄', '북적', '소음', '시끌'],
    'parking': ['주차', '주차장', '협소', '무료', '유료', '어렵', '불가']
}

def judge_visit(text, restaurant_name):
    """Check if this is a restaurant visit post"""
    # Exclude obvious non-restaurant content
    exclude_keywords = ['부동산', '네일', '에스테틱', '영화', '구인', '설치', '크리닝', '미용', '애견', '카페']

    for keyword in exclude_keywords:
        if keyword in text:
            return False

    # Check for restaurant visit indicators
    restaurant_keywords = ['맛집', '방문', '먹', '음식', '돈까스', '치킨', '곱창', '족발', '국밥', '라멘',
                          '계치킨', '곱장', '추어탕', '짜장', '짬뽕', '참치', '떡볶이', '차', '모듬', '식당',
                          '가게', '한우', '소곱창', '회', '버거', '수제', '라멘', '오마카세', '백반', '분식',
                          '해장국', '칼국수', '알려', '메뉴', '주문', '반찬', '맛', '수육']

    count = 0
    for keyword in restaurant_keywords:
        if keyword in text.lower():
            count += 1

    return count >= 3

def has_complaint(text, category_keywords):
    """Check if text contains complaint about a category"""
    complaint_negators = ['아니라', '없', '괜찮', '좋', '맛있', '친절', '넓', '깨끗', '빠르', '싸', '가성비', '정말']

    # Find sentences/phrases with category keywords
    for keyword in category_keywords:
        if keyword in text:
            # Extract surrounding context (rough approach)
            idx = text.find(keyword)
            context = text[max(0, idx-20):min(len(text), idx+30)]

            # Check for complaint indicators
            negation_words = ['하지만', '그런데', '아쉽', '없', '부족', '부족', '나쁜', '안', '못', '문제', '단점',
                            '어려', '힘들', '답답', '답답', '짜증', '싫', '별로', '그냥', '그랬', '적었']

            is_complaint = False
            for neg_word in negation_words:
                if neg_word in context or neg_word in text[max(0, idx-50):min(len(text), idx+50)]:
                    is_complaint = True
                    break

            # Check surrounding sentences
            sentences = text.split('.')
            for sent in sentences:
                if keyword in sent:
                    # Look for complaint indicators
                    if any(neg in sent for neg in ['길다', '어렵', '없다', '부족', '아쉽', '좁', '불친절',
                                                     '느리', '더럽', '비싸', '시끄', '협소']):
                        return True

            if is_complaint:
                return True

    return False

def judge_target(text, restaurant_name):
    """Check if complaint targets the named restaurant"""
    complaint_patterns = ['불만', '아쉽', '별로', '단점', '문제', '어렵', '불친절', '느리', '비싸',
                         '좁', '시끄', '청결', '위생', '주차', '웨이팅']

    # Check if text contains complaints
    has_any_complaint = any(pattern in text for pattern in complaint_patterns)

    if not has_any_complaint:
        return None

    # Check for negation that would redirect complaint elsewhere
    other_shop_patterns = ['다른', '옆', '이웃', '근처', '배달앱', '주변', '건물', '골목']

    for pattern in other_shop_patterns:
        if pattern in text:
            # Check if the pattern is near the complaint
            for complaint in complaint_patterns:
                if complaint in text:
                    idx = text.find(complaint)
                    context = text[max(0, idx-100):min(len(text), idx+100)]
                    if pattern in context:
                        return False

    return True

def analyze_article(article):
    """Analyze single article"""
    text = article['본문']
    restaurant_name = article['상호명']

    # Initialize result
    result = {
        'visit': judge_visit(text, restaurant_name),
        'target': judge_target(text, restaurant_name),
        'wait': has_complaint(text, keywords['wait']),
        'seat': has_complaint(text, keywords['seat']),
        'service': has_complaint(text, keywords['service']),
        'clean': has_complaint(text, keywords['clean']),
        'price': has_complaint(text, keywords['price']),
        'noise': has_complaint(text, keywords['noise']),
        'parking': has_complaint(text, keywords['parking'])
    }

    # If not a restaurant visit, set everything to false/null
    if not result['visit']:
        result['target'] = None
        for key in ['wait', 'seat', 'service', 'clean', 'price', 'noise', 'parking']:
            result[key] = False

    return result

# Process all articles
print(f"Processing {len(batch_data)} articles...")

result = {}
for idx, article in enumerate(batch_data, 1):
    article_id = article['id']
    result[article_id] = analyze_article(article)

    if idx % 20 == 0:
        print(f"  {idx}/{len(batch_data)} completed")

print(f"\nTotal articles processed: {len(result)}")

# Save result
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=0)

print(f"Results saved to: {output_path}")

# Print summary
visit_count = sum(1 for v in result.values() if v['visit'])
target_count = sum(1 for v in result.values() if v['target'] == True)
print(f"\nSummary:")
print(f"  Restaurant visits: {visit_count}/{len(result)}")
print(f"  With complaints about target restaurant: {target_count}/{len(result)}")
