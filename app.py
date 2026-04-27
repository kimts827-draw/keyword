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

# [네이버 데이터랩 API 호출 - 성별/연령 분석]
def get_datalab_analysis(keyword):
    url = "https://openapi.naver.com/v1/datalab/search"
    headers = {"X-Naver-Client-Id": CLIENT_ID, "X-Naver-Client-Secret": CLIENT_SECRET, "Content-Type": "application/json"}
    
    # 최근 1개월 데이터 분석
    end_date = datetime.datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    
    body = {
        "startDate": start_date, "endDate": end_date, "timeUnit": "month",
        "keywordGroups": [{"groupName": keyword, "keywords": [keyword]}]
    }
    
    # 성별 분석
    res_gender = requests.post(url.replace("search", "share/gender"), headers=headers, json=body).json()
    # 연령 분석
    res_age = requests.post(url.replace("search", "share/age"), headers=headers, json=body).json()
    
    return res_gender, res_age

# ==========================================
# [분석 및 크롤링 로직]
# ==========================================
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
                metrics["tag"] += len(s.select(".blog2_post_tag_area a, .item_tag")) # 해시태그 패턴
                metrics["title"] += len(BeautifulSoup(item['title'], "html.parser").get_text().replace(" ", ""))
                metrics["count"] += 1
        except: continue

    if metrics["count"] == 0: return None
    
    # 상위 노출 시 예상 일 방문자 계산 (CTR 10% 가정)
    expected_daily = int((total_vol / 30) * 0.1)
    
    return {
        "text": int(metrics["text_len"]/metrics["count"]), "img": int(metrics["img"]/metrics["count"]),
        "kw": int(metrics["kw"]/metrics["count"]), "tag": int(metrics["tag"]/metrics["count"]),
        "title": int(metrics["title"]/len(items)), "visitors": expected_daily
    }

# ==========================================
# [시각화 컴포넌트]
# ==========================================
def render_user_analysis(keyword):
    g_data, a_data = get_datalab_analysis(keyword)
    
    if 'results' in g_data:
        st.markdown(f"#### 📊 '{keyword}' 검색 사용자 심층 분석")
        c1, c2 = st.columns([1, 2])
        
        # 성별 비율 (최근 데이터 기준)
        with c1:
            g_res = g_data['results'][0]['data']
            if g_res:
                f_ratio = next((x['share'] for x in g_res if x.get('group') == 'f'), 50)
                m_ratio = 100 - f_ratio
                st.write("**성별 비중**")
                st.markdown(f"""
                <div style="background:#eee; border-radius:15px; height:25px; display:flex; overflow:hidden;">
                    <div style="width:{f_ratio}%; background:#ff4b4b; color:white; text-align:center; font-size:12px;">여성</div>
                    <div style="width:{m_ratio}%; background:#1c83e1; color:white; text-align:center; font-size:12px;">남성</div>
                </div>
                """, unsafe_allow_html=True)
                st.caption(f"여성 {f_ratio:.1f}% / 남성 {m_ratio:.1f}%")

        # 연령별 비율
        with c2:
            a_res = a_data['results'][0]['data']
            if a_res:
                age_df = pd.DataFrame(a_res).groupby('group')['share'].mean().reset_index()
                age_df.columns = ['연령대', '비중']
                age_df['연령대'] = age_df['연령대'].map({'10':'10대','20':'20대','30':'30대','40':'40대','50':'50대','60':'60대+'})
                st.write("**연령별 분포**")
                st.bar_chart(age_df.set_index('연령대'), height=150)
        st.divider()

# ==========================================
# [Main UI]
# ==========================================
st.set_page_config(page_title="통합 키워드 분석 시스템", layout="wide")

with st.sidebar:
    st.header("⚙️ 필터 설정")
    blacklist_input = st.text_area("🚫 제외 단어", value="쿠팡, 다이소, 이케아, 삼성, 애플, 나이키, 스타벅스, 알리, 테무")
    blacklist = [word.strip() for word in blacklist_input.split(",") if word.strip()]

st.title("⚡ 마케팅 통합 키워드 분석기")
tab1, tab2, tab3 = st.tabs(["🛒 쇼핑 분석", "📝 블로그 분석", "📑 포스팅 가이드"])

# [TAB 1/2 공통 수집 로직 생략 - 이전 구조 유지]
# ... (기존 fetch_shop_data, fetch_blog_data 함수 사용) ...

with tab1:
    s_keyword = st.text_input("쇼핑 키워드:", key="s_in")
    if st.button("분석 시작", key="s_bt"):
        render_user_analysis(s_keyword)
        # 이후 기존 쇼핑 데이터 추출 로직 진행...

with tab2:
    b_keyword = st.text_input("블로그 키워드:", key="b_in")
    if st.button("분석 시작", key="b_bt"):
        render_user_analysis(b_keyword)
        # 이후 기존 블로그 데이터 추출 로직 진행...

with tab3:
    st.subheader("📝 상위 노출을 위한 포스팅 가이드")
    g_keyword = st.text_input("타겟 키워드 입력:", placeholder="예: 자동차 방향제 추천")
    
    if st.button("가이드 생성"):
        # 검색량 조회를 위해 먼저 호출
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
                
                st.info("💡 **작성 팁:** 위 데이터는 상위 노출된 글들의 평균치입니다. 최소한 이 기준을 넘기도록 작성하는 것이 유리합니다.")
            else: st.error("블로그 데이터를 읽어올 수 없습니다.")
        else: st.error("해당 키워드의 검색량 정보를 찾을 수 없습니다.")