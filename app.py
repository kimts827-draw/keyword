import time
import requests
import pandas as pd
import hashlib
import hmac
import base64
import datetime
import io
import streamlit as st

# ==========================================
# [API 키 세팅] - 본인의 키로 변경 필수
# ==========================================
CUSTOMER_ID = "1166309"
API_KEY = "0100000000ed631c21265bcd5054bf3b1be463722f0b7ff9b796fe9002773230721f0a56fc"
SECRET_KEY = "AQAAAADtYxwhJlvNUFS/OxvkY3IvUr3tb0gFwAHJxLYqDHP+7A=="

CLIENT_ID = "H1DS09bkm8JUMQ52NGCW"
CLIENT_SECRET = "eNZ8Mx9hU0"

# ==========================================
# [공통 함수] 네이버 검색광고 서명 생성 및 키워드 추출
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
    
    headers = {
        "X-Timestamp": timestamp,
        "X-API-KEY": API_KEY,
        "X-Customer": str(CUSTOMER_ID),
        "X-Signature": signature
    }
    
    params = {"hintKeywords": seed_keyword, "showDetail": 1}
    resp = requests.get(base_url + path, params=params, headers=headers)
    
    if resp.status_code != 200:
        st.error(f"검색광고 API 연동 실패 (에러코드: {resp.status_code}). API 키를 확인하세요.")
        return []
    
    return resp.json().get('keywordList', [])

# ==========================================
# [웹페이지 UI 및 탭 구성]
# ==========================================
st.set_page_config(page_title="통합 키워드 분석기", layout="wide")
st.title("통합 키워드 데이터 분석 시스템")
st.write("탭을 선택하여 목적에 맞는 키워드 데이터를 추출하세요.")
st.divider()

# 탭 생성
tab1, tab2 = st.tabs(["🛒 쇼핑 키워드 분석", "📝 블로그 키워드 분석"])

# ------------------------------------------
# [TAB 1] 쇼핑 키워드 분석 로직
# ------------------------------------------
with tab1:
    st.subheader("🛒 쇼핑 키워드 데이터 추출기")
    shop_seed = st.text_input("쇼핑 기준 키워드를 입력하세요:", placeholder="예: 차량용방향제", key="shop_input")
    
    if st.button("쇼핑 데이터 분석 시작", type="primary", key="shop_btn"):
        if shop_seed.strip() == "":
            st.warning("키워드를 입력해 주세요.")
        else:
            keyword_list = get_base_keywords(shop_seed)
            total_count = len(keyword_list)
            
            if total_count > 0:
                st.success(f"총 {total_count}개의 연관 키워드를 분석합니다.")
                results = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for idx, item in enumerate(keyword_list, 1):
                    rel_keyword = item['relKeyword']
                    total_vol = (item['monthlyPcQcCnt'] if isinstance(item['monthlyPcQcCnt'], int) else 0) + \
                                (item['monthlyMobileQcCnt'] if isinstance(item['monthlyMobileQcCnt'], int) else 0)
                    
                    shop_url = "https://openapi.naver.com/v1/search/shop.json"
                    shop_headers = {"X-Naver-Client-Id": CLIENT_ID, "X-Naver-Client-Secret": CLIENT_SECRET}
                    shop_resp = requests.get(shop_url, params={"query": rel_keyword, "display": 1}, headers=shop_headers)
                    
                    product_count = 0
                    category = "없음"
                    
                    if shop_resp.status_code == 200:
                        shop_data = shop_resp.json()
                        product_count = shop_data.get('total', 0)
                        if product_count > 0 and shop_data.get('items'):
                            item_info = shop_data['items'][0]
                            categories = [item_info.get('category1', ''), item_info.get('category2', ''), 
                                          item_info.get('category3', ''), item_info.get('category4', '')]
                            category = " > ".join([c for c in categories if c])
                            
                    competition = round(product_count / total_vol, 2) if total_vol > 0 else 0
                    conversion = round((total_vol / (product_count + 1)) * 100, 2)
                    
                    results.append({
                        "연관키워드": rel_keyword,
                        "쇼핑 카테고리": category,
                        "월 검색량": total_vol,
                        "상품수": product_count,
                        "경쟁률(포화도)": competition,
                        "쇼핑전환기회": conversion
                    })
                    
                    progress_bar.progress(idx / total_count)
                    status_text.text(f"[{idx}/{total_count}] 쇼핑 데이터 분석 중: {rel_keyword}")
                    time.sleep(0.12)
                
                status_text.text("✅ 쇼핑 데이터 수집 완료!")
                df_shop = pd.DataFrame(results)
                st.dataframe(df_shop, use_container_width=True)
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    df_shop.to_excel(writer, index=False, sheet_name='Shop_Data')
                
                file_name = f"{shop_seed}_쇼핑분석_{datetime.datetime.now().strftime('%y%m%d_%H%M')}.xlsx"
                st.download_button("📥 쇼핑 엑셀 다운로드", buffer.getvalue(), file_name, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ------------------------------------------
# [TAB 2] 블로그 키워드 분석 로직
# ------------------------------------------
with tab2:
    st.subheader("📝 블로그 키워드 데이터 추출기")
    blog_seed = st.text_input("블로그 기준 키워드를 입력하세요:", placeholder="예: 세차장 창업", key="blog_input")
    
    if st.button("블로그 데이터 분석 시작", type="primary", key="blog_btn"):
        if blog_seed.strip() == "":
            st.warning("키워드를 입력해 주세요.")
        else:
            keyword_list = get_base_keywords(blog_seed)
            total_count = len(keyword_list)
            
            if total_count > 0:
                st.success(f"총 {total_count}개의 연관 키워드를 분석합니다.")
                results = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for idx, item in enumerate(keyword_list, 1):
                    rel_keyword = item['relKeyword']
                    total_vol = (item['monthlyPcQcCnt'] if isinstance(item['monthlyPcQcCnt'], int) else 0) + \
                                (item['monthlyMobileQcCnt'] if isinstance(item['monthlyMobileQcCnt'], int) else 0)
                    
                    # 네이버 블로그 검색 API 호출
                    blog_url = "https://openapi.naver.com/v1/search/blog.json"
                    blog_headers = {"X-Naver-Client-Id": CLIENT_ID, "X-Naver-Client-Secret": CLIENT_SECRET}
                    blog_resp = requests.get(blog_url, params={"query": rel_keyword, "display": 1}, headers=blog_headers)
                    
                    blog_total = 0
                    
                    if blog_resp.status_code == 200:
                        blog_data = blog_resp.json()
                        blog_total = blog_data.get('total', 0)
                    
                    # 블로그 지표 계산
                    # 블로그 포화도: 월 검색량 대비 누적 문서가 얼마나 많은가 (높을수록 레드오션)
                    saturation = round(blog_total / total_vol, 2) if total_vol > 0 else 0
                    
                    # 노출 기회: 문서 1개당 가져갈 수 있는 예상 검색량 파이 (높을수록 상위노출 시 유리)
                    opportunity = round(total_vol / (blog_total + 1) * 100, 2)
                    
                    results.append({
                        "연관키워드": rel_keyword,
                        "월간 검색량": total_vol,
                        "블로그 누적 발행량": blog_total,
                        "블로그 포화도(경쟁도)": saturation,
                        "노출 기회(블루오션 지수)": opportunity
                    })
                    
                    progress_bar.progress(idx / total_count)
                    status_text.text(f"[{idx}/{total_count}] 블로그 데이터 분석 중: {rel_keyword}")
                    time.sleep(0.12)
                
                status_text.text("✅ 블로그 데이터 수집 완료!")
                df_blog = pd.DataFrame(results)
                st.dataframe(df_blog, use_container_width=True)
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    df_blog.to_excel(writer, index=False, sheet_name='Blog_Data')
                
                file_name = f"{blog_seed}_블로그분석_{datetime.datetime.now().strftime('%y%m%d_%H%M')}.xlsx"
                st.download_button("📥 블로그 엑셀 다운로드", buffer.getvalue(), file_name, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")