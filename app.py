import time
import requests
import pandas as pd
import hashlib
import hmac
import base64
import datetime
import io
import re
import json
import streamlit as st
import concurrent.futures
from bs4 import BeautifulSoup

# ==========================================
# [API 키 세팅] - 본인의 실제 키로 반드시 변경하세요!
# ==========================================
CUSTOMER_ID = "1166309"
API_KEY = "0100000000ed631c21265bcd5054bf3b1be463722f0b7ff9b796fe9002773230721f0a56fc"
SECRET_KEY = "AQAAAADtYxwhJlvNUFS/OxvkY3IvUr3tb0gFwAHJxLYqDHP+7A=="

CLIENT_ID = "H1DS09bkm8JUMQ52NGCW"
CLIENT_SECRET = "eNZ8Mx9hU0"

# ==========================================
# [공통 함수 및 API 통신]
# ==========================================
def generate_signature(timestamp, method, path, secret_key):
    message = f"{timestamp}.{method}.{path}"
    signature = hmac.new(secret_key.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()
    return base64.b64encode(signature).decode('utf-8')

def get_base_keywords(seed_keyword):
    base_url = "https://api.naver.com"
    path = "/keywordstool"
    timestamp = str(round(time.time() * 1000))
    signature = generate_signature(timestamp, "GET", path, SECRET_KEY)
    headers = {"X-Timestamp": timestamp, "X-API-KEY": API_KEY, "X-Customer": str(CUSTOMER_ID), "X-Signature": signature}
    
    # [수정됨] 띄어쓰기 및 특수문자로 인한 400 에러 방지를 위해 공백 강제 제거
    clean_keyword = seed_keyword.replace(" ", "").strip()
    
    params = {"hintKeywords": clean_keyword, "showDetail": 1}
    
    resp = requests.get(base_url + path, params=params, headers=headers)
    
    # [수정됨] 에러 발생 시 네이버 서버가 보낸 '진짜 거절 사유'를 화면에 출력
    if resp.status_code != 200:
        st.error(f"🚨 검색광고 API 연동 실패 (에러코드: {resp.status_code})")
        st.info(f"네이버 서버 응답 메시지: {resp.text}")
        return None
        
    return resp.json().get('keywordList', [])

# ==========================================
# [분석 및 크롤링 로직 (세분화 및 가짜 황금 격리)]
# ==========================================
def fetch_shop_data(item):
    rel_keyword = item['relKeyword']
    total_vol = (item['monthlyPcQcCnt'] if isinstance(item['monthlyPcQcCnt'], int) else 0) + \
                (item['monthlyMobileQcCnt'] if isinstance(item['monthlyMobileQcCnt'], int) else 0)
    
    shop_url = "https://openapi.naver.com/v1/search/shop.json"
    shop_headers = {"X-Naver-Client-Id": CLIENT_ID, "X-Naver-Client-Secret": CLIENT_SECRET}
    
    try:
        shop_resp = requests.get(shop_url, params={"query": rel_keyword, "display": 1}, headers=shop_headers, timeout=5)
        product_count = shop_resp.json().get('total', 0) if shop_resp.status_code == 200 else 0
        category = "없음"
        if product_count > 0 and shop_resp.json().get('items'):
            item_info = shop_resp.json()['items'][0]
            categories = [item_info.get('category1', ''), item_info.get('category2', ''), 
                          item_info.get('category3', ''), item_info.get('category4', '')]
            category = " > ".join([c for c in categories if c])
    except:
        product_count, category = 0, "통신오류"
        
    competition = round(product_count / total_vol, 2) if total_vol > 0 else 0
    conversion = round((total_vol / (product_count + 1)) * 100, 2)
    
    info_keywords = ['방법', '후기', '추천', '비교', '차이', '원인', '증상', '뜻', '이유', '만들기', '순위', '종류']
    if product_count == 0: keyword_type = "주의 (상품없음)"
    elif any(word in rel_keyword for word in info_keywords): keyword_type = "블로그용 (정보성)"
    elif total_vol > 100 and (product_count / total_vol) < 0.1: keyword_type = "블로그용 (낮은 상품비율)"
    else: keyword_type = "쇼핑용"

    # [업그레이드] 쇼핑 키워드 5단계 세분화 + 브랜드 격리
    grade = "⚪ 일반 (보통)"
    if keyword_type == "쇼핑용":
        if total_vol >= 1000 and competition <= 0.05:
            grade = "🚨 브랜드/오타 의심" # 수치가 비정상적으로 너무 좋은 경우
        elif total_vol >= 500 and competition <= 0.5:
            grade = "💎 다이아 (최상급)"
        elif total_vol >= 300 and competition <= 1.0:
            grade = "🥇 황금 (상급)"
        elif total_vol >= 100 and competition <= 3.0:
            grade = "🟢 틈새 (중급)"
        elif competition > 10.0:
            grade = "🔥 레드오션 (포기)"
        
    return {"키워드 등급": grade, "성향": keyword_type, "연관키워드": rel_keyword, "쇼핑 카테고리": category,
            "월 검색량": total_vol, "상품수": product_count, "경쟁률(포화도)": competition, "쇼핑전환기회": conversion}

def fetch_blog_data(item):
    rel_keyword = item['relKeyword']
    total_vol = (item['monthlyPcQcCnt'] if isinstance(item['monthlyPcQcCnt'], int) else 0) + \
                (item['monthlyMobileQcCnt'] if isinstance(item['monthlyMobileQcCnt'], int) else 0)
    
    blog_url = "https://openapi.naver.com/v1/search/blog.json"
    blog_headers = {"X-Naver-Client-Id": CLIENT_ID, "X-Naver-Client-Secret": CLIENT_SECRET}
    
    blog_total = 0
    for attempt in range(3):
        try:
            blog_resp = requests.get(blog_url, params={"query": rel_keyword, "display": 1}, headers=blog_headers, timeout=5)
            if blog_resp.status_code == 200:
                blog_total = blog_resp.json().get('total', 0)
                break
            elif blog_resp.status_code == 429:
                time.sleep(0.5)
                continue
            else:
                break
        except:
            time.sleep(0.5)
            continue
        
    saturation = round(blog_total / total_vol, 2) if total_vol > 0 else 0
    opportunity = round((total_vol / (blog_total + 1)) * 100, 2)

    # [업그레이드] 블로그 키워드 5단계 세분화 + 이슈 키워드 격리
    grade = "⚪ 일반 (보통)"
    if total_vol >= 1000 and saturation <= 0.1:
        grade = "🚨 브랜드/이슈 의심"
    elif total_vol >= 500 and saturation <= 1.0:
        grade = "💎 다이아 (최상급)"
    elif total_vol >= 300 and saturation <= 2.0:
        grade = "🥇 황금 (상급)"
    elif total_vol >= 100 and saturation <= 5.0:
        grade = "🟢 틈새 (중급)"
    elif saturation > 15.0:
        grade = "🔥 레드오션 (포기)"
    
    return {"키워드 등급": grade, "연관키워드": rel_keyword, "월간 검색량": total_vol, "블로그 누적 발행량": blog_total,
            "블로그 포화도(경쟁도)": saturation, "노출 기회(블루오션 지수)": opportunity}

# ==========================================
# [판매지수 분석]
# ==========================================
def fetch_product_data(url):
    import re

    url = url.strip()

    # 실제 브라우저와 동일한 세션 사용
    session = requests.Session()

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    try:
        # ── Step 1. 상품 페이지 먼저 방문 (쿠키 획득) ────────────
        # 실제 브라우저처럼 상품 페이지를 먼저 열어서 세션 쿠키를 받아옴
        page_resp = session.get(url, headers=headers, timeout=10)
        page_resp.encoding = "utf-8"
        html = page_resp.text

        # ── Step 2. HTML 안의 __NEXT_DATA__ JSON에서 데이터 추출 ──
        # 스마트스토어는 페이지 HTML 안에 __NEXT_DATA__라는 script 태그에
        # 상품 전체 데이터를 JSON으로 내장하고 있음
        next_data_match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            html,
            re.DOTALL
        )

        # ── 임시 디버그: 실제로 어떤 HTML이 오는지 확인 ──────────
        st.code(html[:500], language="html")
        # ─────────────────────────────────────────────────────────

        if next_data_match:
            try:
                next_data = json.loads(next_data_match.group(1))

                # __NEXT_DATA__ 안의 경로 탐색
                props = next_data.get("props", {})
                page_props = props.get("pageProps", {})

                # 상품 데이터가 있는 위치 탐색 (구조가 달라질 수 있어 여러 경로 시도)
                product_data = (
                    page_props.get("initialState", {}).get("product", {}).get("A", {})
                    or page_props.get("initialState", {}).get("productDetail", {})
                    or page_props.get("product", {})
                    or {}
                )

                product      = product_data.get("productInfoResponse", {}).get("product", {}) or product_data
                review_stat  = product_data.get("productReviewInfoResponse", {}) or {}
                channel_data = product_data.get("channelJoinStatusResponse", {}) or {}

                product_name = (
                    product.get("name", "")
                    or product.get("productName", "")
                )[:40]

                price = (
                    product.get("salePrice", 0)
                    or product.get("discountedSalePrice", 0)
                )

                review_count = (
                    review_stat.get("reviewCount", 0)
                    or product.get("reviewCount", 0)
                )

                rating = round(float(
                    review_stat.get("averageReviewScore", 0)
                    or product.get("averageReviewScore", 0)
                    or 0
                ), 1)

                wish_count = (
                    product.get("wishCount", 0)
                    or channel_data.get("wishCount", 0)
                )

                sales_count = product.get("totalSoldQuantity", 0) or 0

                images = product.get("productImages", []) or []
                img_count = len(images)

                reg_date = (product.get("regDate", "") or "")[:10]

                # 데이터가 제대로 왔는지 확인
                if product_name:
                    return {
                        "상품명":   product_name,
                        "가격":     price,
                        "리뷰수":   review_count,
                        "평점":     rating,
                        "찜수":     wish_count,
                        "판매량":   sales_count,
                        "이미지수": img_count,
                        "등록일":   reg_date or "확인불가",
                        "url":      url,
                    }

            except Exception as e:
                pass   # __NEXT_DATA__ 파싱 실패 시 Step 3으로 넘어감

        # ── Step 3. __NEXT_DATA__ 실패 시 HTML에서 직접 추출 ──────
        soup = BeautifulSoup(html, "html.parser")

        # 상품명
        product_name = ""
        name_tag = soup.select_one("meta[property='og:title']")
        if name_tag:
            product_name = name_tag.get("content", "")[:40]

        # 가격
        price = 0
        price_tag = soup.select_one("meta[property='product:price:amount']")
        if price_tag:
            try:
                price = int(price_tag.get("content", "0").replace(",", ""))
            except:
                pass

        # 리뷰수, 평점 — meta 태그에서 추출
        review_count = 0
        rating = 0.0
        review_tag = soup.select_one("meta[property='product:rating:value']")
        review_count_tag = soup.select_one("meta[property='product:rating:count']")
        if review_tag:
            try:
                rating = round(float(review_tag.get("content", "0")), 1)
            except:
                pass
        if review_count_tag:
            try:
                review_count = int(review_count_tag.get("content", "0"))
            except:
                pass

        # 판매량 — 텍스트에서 추출
        sales_count = 0
        sales_match = re.search(r'(\d[\d,]+)\s*개\s*판매', html)
        if sales_match:
            try:
                sales_count = int(sales_match.group(1).replace(",", ""))
            except:
                pass

        # 찜수 — 텍스트에서 추출
        wish_count = 0
        wish_match = re.search(r'(\d[\d,]+)\s*명이\s*찜|찜\s*(\d[\d,]+)', html)
        if wish_match:
            try:
                num = wish_match.group(1) or wish_match.group(2)
                wish_count = int(num.replace(",", ""))
            except:
                pass

        if not product_name:
            return {
                "error": "상품 데이터를 찾을 수 없습니다. 스마트스토어 URL인지 확인해주세요.",
                "url": url
            }

        return {
            "상품명":   product_name,
            "가격":     price,
            "리뷰수":   review_count,
            "평점":     rating,
            "찜수":     wish_count,
            "판매량":   sales_count,
            "이미지수": 0,
            "등록일":   "확인불가",
            "url":      url,
        }

    except Exception as e:
        return {"error": str(e), "url": url}


def calculate_score(data):
    """
    수집된 데이터를 100점 만점으로 점수화
    """
    scores = {}

    # 리뷰 수 (30점)
    r = data.get("리뷰수", 0)
    if r >= 1000:      scores["리뷰"] = 30
    elif r >= 500:     scores["리뷰"] = 25
    elif r >= 200:     scores["리뷰"] = 20
    elif r >= 100:     scores["리뷰"] = 15
    elif r >= 50:      scores["리뷰"] = 10
    elif r >= 10:      scores["리뷰"] = 5
    else:              scores["리뷰"] = 0

    # 평점 (20점)
    rt = data.get("평점", 0)
    if rt >= 4.8:      scores["평점"] = 20
    elif rt >= 4.5:    scores["평점"] = 16
    elif rt >= 4.0:    scores["평점"] = 10
    elif rt >= 3.5:    scores["평점"] = 5
    else:              scores["평점"] = 0

    # 찜 수 (20점)
    w = data.get("찜수", 0)
    if w >= 5000:      scores["찜"] = 20
    elif w >= 1000:    scores["찜"] = 16
    elif w >= 500:     scores["찜"] = 12
    elif w >= 100:     scores["찜"] = 8
    elif w >= 10:      scores["찜"] = 4
    else:              scores["찜"] = 0

    # 판매량 (20점) — 비공개면 0점 처리
    s = data.get("판매량", 0)
    if s >= 10000:     scores["판매량"] = 20
    elif s >= 5000:    scores["판매량"] = 16
    elif s >= 1000:    scores["판매량"] = 12
    elif s >= 500:     scores["판매량"] = 8
    elif s >= 100:     scores["판매량"] = 4
    else:              scores["판매량"] = 0

    # 이미지 수 (10점)
    img = data.get("이미지수", 0)
    if img >= 10:      scores["이미지"] = 10
    elif img >= 6:     scores["이미지"] = 7
    elif img >= 3:     scores["이미지"] = 4
    else:              scores["이미지"] = 0

    scores["총점"] = sum(v for k, v in scores.items() if k != "총점")
    return scores

def analyze_top_blogs(urls_input, target_keyword, total_vol):
    """
    사용자가 직접 입력한 URL 목록을 분석.
    urls_input: 줄바꿈으로 구분된 URL 문자열
    """

    # ── 내부 헬퍼 1. 절사평균 ─────────────────────────────────────
    def trim_mean(values, trim=0.1):
        if not values:
            return 0
        if len(values) < 4:
            return int(sum(values) / len(values))
        values_sorted = sorted(values)
        cut = max(1, int(len(values_sorted) * trim))
        trimmed = values_sorted[cut:-cut]
        return int(sum(trimmed) / len(trimmed)) if trimmed else 0

    # ── 내부 헬퍼 2. 비본문 제거 후 순수 글자수 추출 ────────────
    def extract_clean_text(soup):
        REMOVE_SELECTORS = [
            "script", "style", "iframe",
            ".se-author", ".se-publishDate",
            ".wrap_btn_post", ".post_tag",
            ".comment_box", ".post_footer",
            ".__se_toc_wrapper", ".se-module-oglink",
            ".se-sticker", ".se-documentTitle",
        ]
        content = (
            soup.select_one(".se-main-container")
            or soup.select_one("#postViewArea")
            or soup.select_one(".post_ct")
            or soup.select_one(".__se_doc_viewer")
        )
        if not content:
            return "", None
        for selector in REMOVE_SELECTORS:
            for tag in content.select(selector):
                tag.decompose()
        raw = content.get_text(" ", strip=True)
        return "".join(raw.split()), content

    # ── 내부 헬퍼 3. 실제 본문 이미지만 카운트 ──────────────────
    def count_real_images(content_area):
        EXCLUDE_PATTERNS = [
            "sticker", "emoticon", "emoji",
            "static.naver.net", "dthumb.phinf",
            "storep-phinf", "profile", "avatar",
            "favicon", "btnplay", "ico_", "icon",
        ]
        count = 0
        for img in content_area.find_all("img"):
            src = (img.get("src") or img.get("data-lazy-src") or "").lower()
            alt = (img.get("alt") or "").lower()
            if any(pat in src or pat in alt for pat in EXCLUDE_PATTERNS):
                continue
            width = img.get("width", "")
            try:
                if width and int(str(width).replace("px", "")) < 100:
                    continue
            except ValueError:
                pass
            count += 1
        return count

    # ── 내부 헬퍼 4. 순위별 CTR 반영 예상 방문자 ─────────────────
    def estimate_daily_visitors(total_vol):
        CTR_BY_RANK = {1: 0.28, 2: 0.15, 3: 0.09, 4: 0.06, 5: 0.04}
        if total_vol > 10000:
            penalty = 0.6
        elif total_vol > 3000:
            penalty = 0.75
        else:
            penalty = 1.0
        return {
            "1위_예상": int((total_vol / 30) * CTR_BY_RANK[1] * penalty),
            "3위_예상": int((total_vol / 30) * CTR_BY_RANK[3] * penalty),
            "5위_예상": int((total_vol / 30) * CTR_BY_RANK[5] * penalty),
        }

    # ── 내부 헬퍼 5. 단일 URL 크롤링 ────────────────────────────
    def crawl_one(link):
        try:
            if "m.blog.naver.com" not in link:
                mob_link = (
                    link.replace("https://blog.naver.com/", "https://m.blog.naver.com/")
                        .replace("http://blog.naver.com/", "https://m.blog.naver.com/")
                )
            else:
                mob_link = link

            req_headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9",
                "Referer": "https://search.naver.com",
            }

            resp = requests.get(mob_link, headers=req_headers, timeout=8)
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")

            clean_text, content_area = extract_clean_text(soup)
            if not content_area or not clean_text:
                return None, {"url": mob_link, "사유": "본문 영역 탐색 실패 (JS 렌더링 포스팅일 수 있음)"}

            meta_title = soup.select_one("meta[property='og:title']")
            plain_title = soup.select_one("title")
            if meta_title:
                title_text = meta_title.get("content", "")
            elif plain_title:
                title_text = plain_title.get_text()
            else:
                title_text = ""

            # 소제목 수 (h2, h3, h4 태그)
            headings = len(content_area.select("h2, h3, h4, .se-heading"))

            # 문단 수
            paragraphs = len(content_area.select(
                "p, .se-text-paragraph, .se-module-text"
            ))

            # 내부 링크 수 (blog.naver.com)
            internal_links = len([
                a for a in content_area.find_all("a", href=True)
                if "blog.naver.com" in a["href"]
            ])

            # 외부 링크 수
            external_links = len([
                a for a in content_area.find_all("a", href=True)
                if "blog.naver.com" not in a["href"]
                and a["href"].startswith("http")
            ])

            # 동영상 포함 여부
            has_video = bool(
                content_area.select_one(
                    "iframe, video, .se-module-video, embed"
                )
            )

            # 발행일 추출
            pub_date = ""
            date_tag = (
                soup.select_one("meta[property='article:published_time']")
                or soup.select_one(".se-publishDate")
                or soup.select_one(".blog_date")
            )
            if date_tag:
                pub_date = (
                    date_tag.get("content", "") or date_tag.get_text()
                ).strip()[:10]

            return {
                "text_len":       len(clean_text),
                "img":            count_real_images(content_area),
                "kw":             content_area.get_text().count(target_keyword),
                "headings":       headings,
                "paragraphs":     paragraphs,
                "internal_links": internal_links,
                "external_links": external_links,
                "has_video":      has_video,
                "원본_url":       link,
                "글자수":         len(clean_text),
                "이미지수":       count_real_images(content_area),
                "키워드반복":     content_area.get_text().count(target_keyword),
                "소제목수":       headings,
                "문단수":         paragraphs,
                "내부링크":       internal_links,
                "외부링크":       external_links,
                "동영상":         "✅" if has_video else "❌",
                "발행일":         pub_date if pub_date else "확인불가",
            }, None

        except Exception as e:
            return None, {"url": link, "사유": str(e)}

    # ── 메인 로직 ─────────────────────────────────────────────────

    # URL 파싱 — 줄바꿈 또는 쉼표로 구분, 공백 제거, 빈 줄 제거
    urls = [
        u.strip() for u in urls_input.replace(",", "\n").splitlines()
        if u.strip() and "blog.naver.com" in u
    ]

    if not urls:
        return None, [], "blog.naver.com URL을 입력해주세요."

    if len(urls) > 10:
        return None, [], "URL은 최대 10개까지 입력 가능합니다."

    # 병렬 크롤링
    metrics = {
        "text_len": [], "img": [], "kw": [],
        "headings": [], "paragraphs": [],
        "internal_links": [], "external_links": [],
    }
    failed_urls = []
    per_post_data = []   # 포스팅별 개별 데이터 (테이블용)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        crawl_results = list(executor.map(crawl_one, urls))

    for result, error in crawl_results:
        if error:
            failed_urls.append(error)
        elif result:
            metrics["text_len"].append(result["text_len"])
            metrics["img"].append(result["img"])
            metrics["kw"].append(result["kw"])
            metrics["headings"].append(result["headings"])
            metrics["paragraphs"].append(result["paragraphs"])
            metrics["internal_links"].append(result["internal_links"])
            metrics["external_links"].append(result["external_links"])
            per_post_data.append({
                "URL":      result["원본_url"],
                "글자수":   f"{result['글자수']:,}자",
                "이미지":   f"{result['이미지수']}개",
                "키워드반복": f"{result['키워드반복']}회",
                "소제목":   f"{result['소제목수']}개",
                "문단수":   f"{result['문단수']}개",
                "내부링크": f"{result['내부링크']}개",
                "외부링크": f"{result['외부링크']}개",
                "동영상":   result["동영상"],
                "발행일":   result["발행일"],
            })

    if not metrics["text_len"]:
        return None, failed_urls, "분석 성공한 포스팅이 없습니다."

    visitors = estimate_daily_visitors(total_vol)

    summary = {
        "text":           trim_mean(metrics["text_len"]),
        "img":            trim_mean(metrics["img"]),
        "kw":             trim_mean(metrics["kw"]),
        "headings":       trim_mean(metrics["headings"]),
        "paragraphs":     trim_mean(metrics["paragraphs"]),
        "internal_links": trim_mean(metrics["internal_links"]),
        "external_links": trim_mean(metrics["external_links"]),
        "sample_count":   len(metrics["text_len"]),
    }

    return summary, failed_urls, per_post_data

# ==========================================
# [기기별 사용자 비율 컴포넌트]
# ==========================================
def render_device_ratio(keyword_list, seed_keyword):
    target_data = next((item for item in keyword_list if item['relKeyword'].replace(" ", "") == seed_keyword.replace(" ", "")), None)
    
    if target_data:
        pc_v = target_data['monthlyPcQcCnt'] if isinstance(target_data['monthlyPcQcCnt'], int) else 0
        mo_v = target_data['monthlyMobileQcCnt'] if isinstance(target_data['monthlyMobileQcCnt'], int) else 0
        tot_v = pc_v + mo_v
        
        if tot_v > 0:
            pc_percent = int((pc_v / tot_v) * 100)
            mo_percent = 100 - pc_percent
            
            st.markdown(f"#### 📱 '{seed_keyword}' 기기별 검색 사용자 비율")
            st.markdown(f"""
            <div style="display: flex; height: 35px; border-radius: 8px; overflow: hidden; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <div style="width: {mo_percent}%; background-color: #2ECC71; display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: 14px;">모바일 {mo_percent}%</div>
                <div style="width: {pc_percent}%; background-color: #E0E0E0; display: flex; align-items: center; justify-content: center; color: #333; font-weight: bold; font-size: 14px;">PC {pc_percent}%</div>
            </div>
            """, unsafe_allow_html=True)
            st.caption(f"* 모바일 검색량: {mo_v:,}건 / PC 검색량: {pc_v:,}건 (최근 1개월 기준)")
            st.divider()

# ==========================================
# [Main UI]
# ==========================================
st.set_page_config(page_title="통합 키워드 분석 시스템", layout="wide")

with st.sidebar:
    st.header("⚙️ 필터 설정")
    blacklist_input = st.text_area("🚫 제외 단어", value="쿠팡, 다이소, 이케아, 삼성, 애플, 나이키, 스타벅스, 알리, 테무")
    blacklist = [word.strip() for word in blacklist_input.split(",") if word.strip()]
    st.divider()
    st.markdown("""
    **📊 키워드 등급 기준**
    - 💎 **다이아:** 검색량 500↑ & 경쟁률 0.5↓ (최상)
    - 🥇 **황금:** 검색량 300↑ & 경쟁률 1.0↓ (상급)
    - 🟢 **틈새:** 검색량 100↑ & 경쟁률 3.0↓ (중급, 현실적 타점)
    - 🚨 **의심:** 수치가 비정상적으로 좋음 (상표권 주의)
    - 🔥 **레드오션:** 경쟁률 10.0 초과 (진입 주의)
    """)

st.title("⚡ 마케팅 통합 키워드 분석기")
tab1, tab2, tab3, tab4 = st.tabs(["🛒 쇼핑 분석", "📝 블로그 분석", "📑 포스팅 가이드", "📊 판매지수 비교"])

with tab1:
    s_keyword = st.text_input("쇼핑 키워드:", key="s_in", placeholder="예: 차량용방향제")
    if st.button("분석 시작", key="s_bt"):
        if s_keyword.strip():
            raw_keyword_list = get_base_keywords(s_keyword)
            
            # [수정됨] API 실패(None 반환) 시 로직 중단
            if raw_keyword_list is None:
                st.stop()
                
            if len(raw_keyword_list) == 0:
                st.warning("해당 키워드에 대한 연관 검색어가 없습니다.")
                st.stop()
            
            render_device_ratio(raw_keyword_list, s_keyword)
                
            original_count = len(raw_keyword_list)
            keyword_list = [item for item in raw_keyword_list if not any(b_word in item['relKeyword'] for b_word in blacklist)]
            total_count = len(keyword_list)
            
            if total_count > 0:
                st.info(f"블랙리스트 {original_count - total_count}개 제외, 총 **{total_count}개** 연관키워드 수집 중...")
                results = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    futures = {executor.submit(fetch_shop_data, item): item for item in keyword_list}
                    for idx, future in enumerate(concurrent.futures.as_completed(futures), 1):
                        results.append(future.result())
                        progress_bar.progress(idx / total_count)
                        status_text.text(f"[{idx}/{total_count}] 병렬 수집 중...")
                        time.sleep(0.02) 
                
                status_text.text("✅ 수집 완료! '키워드 등급' 컬럼에서 황금 키워드를 찾아보세요.")
                df_shop = pd.DataFrame(results)
                
                st.dataframe(df_shop, use_container_width=True)
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    df_shop.to_excel(writer, index=False, sheet_name='Shop')
                st.download_button("📥 엑셀 다운로드", buffer.getvalue(), f"{s_keyword}_쇼핑.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab2:
    b_keyword = st.text_input("블로그 키워드:", key="b_in", placeholder="예: 세차장 창업")
    if st.button("분석 시작", key="b_bt"):
        if b_keyword.strip():
            raw_keyword_list = get_base_keywords(b_keyword)
            
            # [수정됨] API 실패(None 반환) 시 로직 중단
            if raw_keyword_list is None:
                st.stop()
                
            if len(raw_keyword_list) == 0:
                st.warning("해당 키워드에 대한 연관 검색어가 없습니다.")
                st.stop()
            
            render_device_ratio(raw_keyword_list, b_keyword)
                
            original_count = len(raw_keyword_list)
            keyword_list = [item for item in raw_keyword_list if not any(b_word in item['relKeyword'] for b_word in blacklist)]
            total_count = len(keyword_list)
            
            if total_count > 0:
                st.info(f"블랙리스트 {original_count - total_count}개 제외, 총 **{total_count}개** 연관키워드 수집 중...")
                results = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    futures = {executor.submit(fetch_blog_data, item): item for item in keyword_list}
                    for idx, future in enumerate(concurrent.futures.as_completed(futures), 1):
                        results.append(future.result())
                        progress_bar.progress(idx / total_count)
                        status_text.text(f"[{idx}/{total_count}] 병렬 수집 중...")
                        time.sleep(0.02) 
                
                status_text.text("✅ 수집 완료! '키워드 등급' 컬럼에서 황금 키워드를 찾아보세요.")
                df_blog = pd.DataFrame(results)
                st.dataframe(df_blog, use_container_width=True)
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    df_blog.to_excel(writer, index=False, sheet_name='Blog')
                st.download_button("📥 엑셀 다운로드", buffer.getvalue(), f"{b_keyword}_블로그.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab3:
    st.subheader("📝 상위 노출을 위한 포스팅 가이드")

    st.markdown("""
    **사용 방법**
    1. 네이버에서 타겟 키워드를 직접 검색
    2. 상위 노출된 블로그 포스팅 URL을 3~5개 복사
    3. 아래에 붙여넣기 (한 줄에 하나씩)
    """)

    g_keyword = st.text_input(
        "타겟 키워드",
        placeholder="예: 자동차 방향제 추천"
    )
    urls_input = st.text_area(
        "분석할 포스팅 URL (한 줄에 하나씩, 최대 10개)",
        placeholder=(
            "https://blog.naver.com/example1/123456\n"
            "https://blog.naver.com/example2/234567\n"
            "https://blog.naver.com/example3/345678"
        ),
        height=160,
    )

    if st.button("가이드 생성"):
        if not g_keyword.strip():
            st.warning("타겟 키워드를 입력해주세요.")
            st.stop()
        if not urls_input.strip():
            st.warning("분석할 포스팅 URL을 입력해주세요.")
            st.stop()

        # 검색량 조회
        kw_data = get_base_keywords(g_keyword)
        if kw_data is None:
            st.stop()

        target = next(
            (item for item in kw_data
             if item['relKeyword'].replace(" ", "") == g_keyword.replace(" ", "")),
            None
        )
        vol = 0
        if target:
            vol = (target['monthlyPcQcCnt'] or 0) + (target['monthlyMobileQcCnt'] or 0)

        with st.spinner("포스팅 분석 중..."):
            result = analyze_top_blogs(urls_input, g_keyword, vol)

        # 반환값 언패킹
        res, failed_urls, extra = result

        # URL 오류 또는 검증 실패 메시지 처리
        if res is None:
            st.error(f"❌ {extra}")
            st.stop()

        # ── 요약 지표 ──────────────────────────────────────────────
        st.success(
            f"'{g_keyword}' 포스팅 **{res['sample_count']}개** 분석 완료"
            + (f" | 월 검색량: {vol:,}" if vol else "")
        )

        c1, c2, c3 = st.columns(3)
        c4, c5, c6 = st.columns(3)

        c1.metric("권장 글자 수",  f"{res['text']:,}자")
        c2.metric("평균 이미지",   f"{res['img']}개")
        c3.metric("키워드 반복",   f"{res['kw']}회")
        c4.metric("소제목 수",     f"{res['headings']}개",
                  help="h2~h4 태그 기준. 글 구조화 정도를 나타냅니다.")
        c5.metric("문단 수",       f"{res['paragraphs']}개",
                  help="단락 수. 높을수록 읽기 쉬운 구조입니다.")
        c6.metric("외부 링크 수",  f"{res['external_links']}개",
                  help="출처·참고자료 링크 수. 신뢰도 지표로 활용됩니다.")
        

        # ── 포스팅별 개별 데이터 테이블 ───────────────────────────
        st.divider()
        st.markdown("##### 📋 포스팅별 상세 데이터")
        st.dataframe(
            pd.DataFrame(extra),
            use_container_width=True,
            hide_index=True,
        )

        # ── 크롤링 실패 현황 ───────────────────────────────────────
        if failed_urls:
            with st.expander(f"⚠️ 분석 실패 {len(failed_urls)}건 (클릭해서 확인)"):
                st.dataframe(pd.DataFrame(failed_urls), use_container_width=True)
                st.caption("실패한 포스팅은 JS 렌더링 방식이거나 네이버가 접근을 차단했을 수 있습니다.")

with tab4:
    st.subheader("📊 판매지수 비교 분석")
    st.caption("스마트스토어 상품 URL을 입력하면 판매지수를 점수화해서 비교합니다.")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### 🔵 내 상품")
        my_url = st.text_input(
            "내 상품 URL",
            placeholder="https://smartstore.naver.com/...",
            key="my_url"
        )
    with col_b:
        st.markdown("#### 🔴 경쟁 상품")
        comp_url = st.text_input(
            "경쟁 상품 URL",
            placeholder="https://smartstore.naver.com/...",
            key="comp_url"
        )

    if st.button("판매지수 분석 시작", key="score_bt"):
        if not my_url.strip() or not comp_url.strip():
            st.warning("두 상품의 URL을 모두 입력해주세요.")
            st.stop()

        with st.spinner("상품 데이터 수집 중..."):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(fetch_product_data, my_url),
                    executor.submit(fetch_product_data, comp_url),
                ]
                my_data, comp_data = [f.result() for f in futures]

        # 오류 체크
        if "error" in my_data:
            st.error(f"❌ 내 상품 수집 실패: {my_data['error']}")
            st.code(f"입력 URL: {my_data['url']}")
            st.stop()
        if "error" in comp_data:
            st.error(f"❌ 경쟁 상품 수집 실패: {comp_data['error']}")
            st.code(f"입력 URL: {comp_data['url']}")
            st.stop()

        my_score   = calculate_score(my_data)
        comp_score = calculate_score(comp_data)

        # ── 총점 비교 ─────────────────────────────────────────
        st.divider()
        c1, c2 = st.columns(2)

        def score_color(score):
            if score >= 80: return "🟢"
            elif score >= 60: return "🟡"
            elif score >= 40: return "🟠"
            else: return "🔴"

        with c1:
            st.markdown(f"### 🔵 {my_data['상품명']}")
            st.metric(
                "총점",
                f"{score_color(my_score['총점'])} {my_score['총점']}점 / 100점",
            )
        with c2:
            st.markdown(f"### 🔴 {comp_data['상품명']}")
            st.metric(
                "총점",
                f"{score_color(comp_score['총점'])} {comp_score['총점']}점 / 100점",
            )

        # ── 항목별 점수 비교 바 ───────────────────────────────
        st.divider()
        st.markdown("#### 📋 항목별 점수 비교")

        ITEMS = [
            ("리뷰",  30, "리뷰수",  "개"),
            ("평점",  20, "평점",    "점"),
            ("찜",    20, "찜수",    "개"),
            ("판매량",20, "판매량",  "개"),
            ("이미지",10, "이미지수","개"),
        ]

        for label, max_score, data_key, unit in ITEMS:
            my_s    = my_score[label]
            comp_s  = comp_score[label]
            my_val   = my_data.get(data_key, 0)
            comp_val = comp_data.get(data_key, 0)

            # 어느 쪽이 부족한지 표시
            if my_s < comp_s:
                gap_msg = f"⚠️ **{label}** 부족 ({my_s}점 vs {comp_s}점) — {comp_val - my_val:,}{unit} 차이"
            elif my_s > comp_s:
                gap_msg = f"✅ **{label}** 우위 ({my_s}점 vs {comp_s}점)"
            else:
                gap_msg = f"➖ **{label}** 동점 ({my_s}점)"

            st.markdown(gap_msg)

            bar_col1, bar_col2 = st.columns(2)
            with bar_col1:
                st.progress(my_s / max_score)
                st.caption(f"🔵 내 상품: {my_val:,}{unit} → {my_s}/{max_score}점")
            with bar_col2:
                st.progress(comp_s / max_score)
                st.caption(f"🔴 경쟁 상품: {comp_val:,}{unit} → {comp_s}/{max_score}점")

        # ── 원본 수집 데이터 ──────────────────────────────────
        st.divider()
        with st.expander("🔍 원본 수집 데이터 확인"):
            d1, d2 = st.columns(2)
            with d1:
                st.markdown("**🔵 내 상품**")
                st.json({k: v for k, v in my_data.items() if k != "url"})
            with d2:
                st.markdown("**🔴 경쟁 상품**")
                st.json({k: v for k, v in comp_data.items() if k != "url"})

        # ── 개선 제안 ────────────────────────────────────────
        st.divider()
        st.markdown("#### 💡 개선 제안")

        suggestions = []
        for label, max_score, data_key, unit in ITEMS:
            my_s   = my_score[label]
            comp_s = comp_score[label]
            if my_s < comp_s:
                diff = comp_data.get(data_key, 0) - my_data.get(data_key, 0)
                if label == "리뷰":
                    suggestions.append(f"📝 리뷰가 **{diff:,}개** 부족합니다. 구매자 리뷰 이벤트를 진행해보세요.")
                elif label == "평점":
                    suggestions.append(f"⭐ 평점이 낮습니다. 상품 품질 및 CS 응대를 점검해보세요.")
                elif label == "찜":
                    suggestions.append(f"❤️ 찜이 **{diff:,}개** 부족합니다. 찜 이벤트나 SNS 홍보를 고려해보세요.")
                elif label == "판매량":
                    suggestions.append(f"🛒 판매량이 부족합니다. 초기 판매를 늘리기 위해 할인 쿠폰 발행을 고려해보세요.")
                elif label == "이미지":
                    suggestions.append(f"🖼️ 상품 이미지가 부족합니다. 다양한 각도의 이미지를 추가해보세요.")

        if suggestions:
            for s in suggestions:
                st.markdown(s)
        else:
            st.success("🎉 모든 항목에서 경쟁 상품 이상입니다!")