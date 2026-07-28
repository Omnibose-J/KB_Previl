import json

input_file = "scratch_bprobe/b1_batch3.json"
output_file = "scratch_bprobe/b1_out_b3_A.json"

with open(input_file, "r", encoding="utf-8") as f:
    data = json.load(f)

output = {}

def has_complaint(text, category):
    text_lower = text.lower()
    
    if category == "wait":
        if any(w in text_lower for w in ["대기", "웨이팅", "줄"]):
            if any(w in text_lower for w in ["길", "오래", "많"]):
                return True
        return False
    elif category == "seat":
        if any(p in text_lower for p in ["좁", "불편", "협소", "자리가 없", "자리 없"]):
            return True
        return False
    elif category == "service":
        if any(p in text_lower for p in ["불친절", "느림", "느린", "노매너"]):
            return True
        return False
    elif category == "clean":
        if any(p in text_lower for p in ["더러", "지저분", "불결"]):
            return True
        return False
    elif category == "price":
        if any(p in text_lower for p in ["비싸", "비쌈", "비싼"]):
            return True
        return False
    elif category == "noise":
        if any(p in text_lower for p in ["시끄러움", "시끄럽", "정신없", "소음"]):
            return True
        return False
    elif category == "parking":
        if "주차" in text_lower:
            if any(p in text_lower for p in ["어렵", "없", "협소"]):
                if "가능" not in text_lower and "무료" not in text_lower:
                    return True
        return False
    return False

def is_restaurant_visit(text, name):
    text_lower = text.lower()
    name_lower = name.lower()
    
    non_rest = ["호텔", "펜션", "숙소", "여행", "관광", "기차", "스위스", "마드리드",
                "베이징", "오사카", "홍콩", "마카오", "네일", "미용실", "복싱",
                "인테리어", "채용", "구인", "명언", "화물운송", "설치사례"]
    if any(k in text_lower for k in non_rest):
        return False
    
    rest_keys = ["맛집", "술집", "호프", "포차", "치킨", "음식점", "식당", "카페",
                 "찌개", "곱창", "족발", "갈비", "고기", "밥", "국", "탕",
                 "초밥", "스시", "국수", "라면", "커피"]
    
    has_rest_keyword = any(k in text_lower for k in rest_keys)
    
    if has_rest_keyword:
        return True
    
    visit_keywords = ["메뉴", "음식", "접시", "밥", "먹", "맛", "음료", "드림"]
    has_visit_keyword = any(k in text_lower for k in visit_keywords)
    
    if has_visit_keyword and "명언" not in text_lower and "호텔" not in text_lower:
        return True
    
    rest_names = ["곱창", "족발", "갈비", "닭", "스시", "초밥", "카페", "호프", "포차",
                  "찌개", "탕", "국", "밥", "국수", "라면", "치킨", "피자"]
    if any(k in name_lower for k in rest_names):
        return True
    
    return False

for item in data:
    id_str = str(item["id"])
    name = item["상호명"]
    text = item["본문"]
    
    visit = is_restaurant_visit(text, name)
    
    has_any = False
    if visit:
        for cat in ["wait", "seat", "service", "clean", "price", "noise", "parking"]:
            if has_complaint(text, cat):
                has_any = True
                break
    
    target = True if has_any else None
    
    output[id_str] = {
        "visit": visit,
        "target": target,
        "wait": has_complaint(text, "wait") if visit else False,
        "seat": has_complaint(text, "seat") if visit else False,
        "service": has_complaint(text, "service") if visit else False,
        "clean": has_complaint(text, "clean") if visit else False,
        "price": has_complaint(text, "price") if visit else False,
        "noise": has_complaint(text, "noise") if visit else False,
        "parking": has_complaint(text, "parking") if visit else False,
    }

with open(output_file, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=0)

print(f"완료: {len(output)}건")
