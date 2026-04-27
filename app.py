import time
import requests
import pandas as pd
import hashlib
import hmac
import base64
import datetime
import io
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


def analyze_top_blogs(target_keyword, total_vol):
    url = "https://openapi.naver.com/v1/search/blog.json"
    headers = {"X-Naver-Client-Id": CLIENT_ID, "X-Naver-Client-Secret": CLIENT_SECRET}
    params = {"query": target_keyword, "display": 3, "sort": "sim"}
    
    resp = requests.get(url, params=params, headers=headers)
    if resp.status_code != 200 or not resp.json().get('items'): return None
        
    items = resp.json().get('items', [])
    metrics = {"text_len": 0, "img": 0, "kw": 0, "tag": 0, "title": 0, "count": 0}
    
    # [정밀화] 실제 크롬 브라우저인 것처럼 헤더를 더욱 상세히 위장
    req_headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    for item in items:
        try:
            # 1. 주소 정규화 (가장 정확한 모바일 주소 체계로 변환)
            # 예: https://blog.naver.com/id/12345 -> https://m.blog.naver.com/id/12345
            link = item['link'].replace("https://blog.naver.com/", "https://m.blog.naver.com/")
            
            res = requests.get(link, headers=req_headers, timeout=5)
            res.encoding = 'utf-8' # 인코딩 강제 고정
            soup = BeautifulSoup(res.text, "html.parser")
            
            # 2. 본문 영역 탐색 (다중 레이어 체크)
            # 신형(se-main-container) -> 구형(post_ct) -> 최후 수단(div) 순으로 탐색
            content_area = soup.select_one(".se-main-container") or soup.select_one("#postViewArea") or soup.select_one(".post_ct")
            
            if content_area:
                # [텍스트 정밀 추출] 불필요한 태그 제거 후 순수 텍스트만 추출
                for s in content_area(["script", "style", "iframe", "header", "footer"]): 
                    s.extract()
                
                # 띄어쓰기 포함하여 텍스트 가져온 뒤, 글자수 셀 때는 공백 제거
                raw_text = content_area.get_text(" ", strip=True)
                clean_text = "".join(raw_text.split()) # 모든 공백 제거
                
                metrics["text_len"] += len(clean_text)
                
                # [이미지 정밀 추출] 광고성 이미지, 아이콘, 스티커(라인프렌즈 등) 제외
                # 네이버 블로그 이미지는 보통 특정 클래스나 경로를 가짐
                all_imgs = content_area.find_all("img")
                real_imgs = []
                for img in all_imgs:
                    src = img.get('src', '')
                    # 스티커(sticker), 프로필(profile), 아이콘(emoji) 관련 경로 제외
                    if 'postfiles' in src or 'blogfiles' in src:
                        if 'static.naver.net' not in src:
                            real_imgs.append(img)
                
                metrics["img"] += len(real_imgs)
                
                # [키워드 반복수] 공백 제거 전 텍스트에서 검색
                metrics["kw"] += raw_text.count(target_keyword)
                
                # [태그 수]
                tags = soup.select(".item_tag, .tag_item, .tag_list a")
                metrics["tag"] += len(tags)
                
                metrics["title"] += len(BeautifulSoup(item['title'], "html.parser").get_text().replace(" ", ""))
                metrics["count"] += 1
                
            time.sleep(0.3) # 네이버의 차단을 피하기 위한 미세한 간격
        except:
            continue

    if metrics["count"] == 0: return None
    
    # 상위 노출 시 예상 일 방문자 계산 (CTR 10%)
    expected_daily = int((total_vol / 30) * 0.1)
    
    return {
        "text": int(metrics["text_len"]/metrics["count"]), 
        "img": int(metrics["img"]/metrics["count"]),
        "kw": int(metrics["kw"]/metrics["count"]), 
        "tag": int(metrics["tag"]/metrics["count"]),
        "title": int(metrics["title"]/len(items)), 
        "visitors": expected_daily
    }

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
tab1, tab2, tab3 = st.tabs(["🛒 쇼핑 분석", "📝 블로그 분석", "📑 포스팅 가이드"])

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
    g_keyword = st.text_input("타겟 키워드 입력:", placeholder="예: 자동차 방향제 추천")
    if st.button("가이드 생성"):
        kw_data = get_base_keywords(g_keyword)
        
        # [수정됨] API 실패(None 반환) 시 로직 중단
        if kw_data is None:
            st.stop()
            
        target = next((item for item in kw_data if item['relKeyword'].replace(" ", "") == g_keyword.replace(" ", "")), None)
        
        if target:
            vol = (target['monthlyPcQcCnt'] or 0) + (target['monthlyMobileQcCnt'] or 0)
            with st.spinner('실시간 포스팅 데이터 분석 중...'):
                res = analyze_top_blogs(g_keyword, vol)
            
            if res:
                st.success(f"'{g_keyword}' 상위 3개 블로그 분석 완료 (월 검색량: {vol:,})")
                c1, c2, c3 = st.columns(3)
                c4, c5, c6 = st.columns(3)
                
                c1.metric("권장 글자 수", f"{res['text']:,}자")
                c2.metric("평균 이미지", f"{res['img']}개")
                c3.metric("키워드 반복", f"{res['kw']}회")
                c4.metric("평균 해시태그", f"{res['tag']}개")
                c5.metric("제목 길이", f"{res['title']}자")
                c6.metric("예상 일 방문자", f"{res['visitors']}명", help="1~3위 이내 노출 시 기대할 수 있는 유입량입니다.")
            else: st.error("블로그 데이터를 읽어올 수 없습니다.")
        else: st.error("해당 키워드의 검색량 정보를 찾을 수 없습니다.")