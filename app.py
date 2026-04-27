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
# [API 키 세팅] - 본인의 키로 변경 필수
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
    params = {"hintKeywords": seed_keyword, "showDetail": 1}
    resp = requests.get(base_url + path, params=params, headers=headers)
    return resp.json().get('keywordList', []) if resp.status_code == 200 else []

# ==========================================
# [분석 및 크롤링 로직 (황금 등급 추가)]
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

    # [신규 추가] 황금 키워드 등급 로직
    grade = "일반"
    if keyword_type == "쇼핑용":
        if total_vol >= 500 and competition <= 1.0:
            grade = "🥇 황금"
        elif total_vol >= 300 and competition <= 2.0:
            grade = "🟢 우수"
        
    return {"키워드 등급": grade, "성향": keyword_type, "연관키워드": rel_keyword, "쇼핑 카테고리": category,
            "월 검색량": total_vol, "상품수": product_count, "경쟁률(포화도)": competition, "쇼핑전환기회": conversion}

def fetch_blog_data(item):
    rel_keyword = item['relKeyword']
    total_vol = (item['monthlyPcQcCnt'] if isinstance(item['monthlyPcQcCnt'], int) else 0) + \
                (item['monthlyMobileQcCnt'] if isinstance(item['monthlyMobileQcCnt'], int) else 0)
    
    blog_url = "https://openapi.naver.com/v1/search/blog.json"
    blog_headers = {"X-Naver-Client-Id": CLIENT_ID, "X-Naver-Client-Secret": CLIENT_SECRET}
    
    try:
        blog_resp = requests.get(blog_url, params={"query": rel_keyword, "display": 1}, headers=blog_headers, timeout=5)
        blog_total = blog_resp.json().get('total', 0) if blog_resp.status_code == 200 else 0
    except: blog_total = 0
        
    saturation = round(blog_total / total_vol, 2) if total_vol > 0 else 0
    opportunity = round((total_vol / (blog_total + 1)) * 100, 2)

    # [신규 추가] 블로그 황금 키워드 로직
    grade = "일반"
    if total_vol >= 500 and saturation <= 2.0:
        grade = "🥇 황금"
    elif total_vol >= 300 and saturation <= 5.0:
        grade = "🟢 우수"
    
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
    req_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    for item in items:
        try:
            res = requests.get(item['link'], headers=req_headers, timeout=5)
            soup = BeautifulSoup(res.text, "html.parser")
            iframe = soup.select_one("iframe#mainFrame")
            if iframe:
                res_real = requests.get("https://blog.naver.com" + iframe["src"], headers=req_headers, timeout=5)
                s = BeautifulSoup(res_real.text, "html.parser")
                content = s.get_text()
                metrics["text_len"] += len(content.replace(" ", ""))
                metrics["img"] += len(s.find_all("img"))
                metrics["kw"] += content.count(target_keyword)
                metrics["tag"] += len(s.select(".blog2_post_tag_area a, .item_tag")) 
                metrics["title"] += len(BeautifulSoup(item['title'], "html.parser").get_text().replace(" ", ""))
                metrics["count"] += 1
        except: continue

    if metrics["count"] == 0: return None
    expected_daily = int((total_vol / 30) * 0.1)
    
    return {"text": int(metrics["text_len"]/metrics["count"]), "img": int(metrics["img"]/metrics["count"]),
            "kw": int(metrics["kw"]/metrics["count"]), "tag": int(metrics["tag"]/metrics["count"]),
            "title": int(metrics["title"]/len(items)), "visitors": expected_daily}

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
    **🥇 황금 키워드 기준**
    - **쇼핑:** 검색량 500이상 & 상품수 비율 1.0 이하
    - **블로그:** 검색량 500이상 & 포화도 2.0 이하
    """)

st.title("⚡ 마케팅 통합 키워드 분석기")
tab1, tab2, tab3 = st.tabs(["🛒 쇼핑 분석", "📝 블로그 분석", "📑 포스팅 가이드"])

with tab1:
    s_keyword = st.text_input("쇼핑 키워드:", key="s_in", placeholder="예: 차량용방향제")
    if st.button("분석 시작", key="s_bt"):
        if s_keyword.strip():
            raw_keyword_list = get_base_keywords(s_keyword)
            
            if raw_keyword_list:
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
                
                # 황금 키워드가 눈에 띄도록 정렬 기능 지원 데이터프레임 출력
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
            
            if raw_keyword_list:
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