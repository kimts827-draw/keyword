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
# [API 키 세팅]
# ==========================================
CUSTOMER_ID = "1166309"
API_KEY = "0100000000ed631c21265bcd5054bf3b1be463722f0b7ff9b796fe9002773230721f0a56fc"
SECRET_KEY = "AQAAAADtYxwhJlvNUFS/OxvkY3IvUr3tb0gFwAHJxLYqDHP+7A=="

CLIENT_ID = "H1DS09bkm8JUMQ52NGCW"
CLIENT_SECRET = "eNZ8Mx9hU0"

def generate_signature(timestamp, method, path, secret_key):
    message = f"{timestamp}.{method}.{path}"
    signature = hmac.new(secret_key.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()
    return base64.b64encode(signature).decode('utf-8')

def get_naver_keyword_data(seed_keyword):
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
        st.error(f"검색광고 API 연동 실패 (에러코드: {resp.status_code}). 키를 확인하세요.")
        return None

    data = resp.json()
    keyword_list = data.get('keywordList', [])
    total_count = len(keyword_list)
    
    if total_count == 0:
        st.warning("조회된 연관 키워드가 없습니다.")
        return None

    st.success(f"총 {total_count}개의 연관 키워드가 발견되었습니다. 데이터 추출을 진행합니다.")
    
    results = []
    
    # 웹페이지 UI 요소: 진행률 바 및 상태 텍스트
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for idx, item in enumerate(keyword_list, 1):
        rel_keyword = item['relKeyword']
        pc_vol = item['monthlyPcQcCnt']
        mo_vol = item['monthlyMobileQcCnt']
        
        pc_vol = 0 if isinstance(pc_vol, str) else pc_vol
        mo_vol = 0 if isinstance(mo_vol, str) else mo_vol
        total_vol = pc_vol + mo_vol
        
        shop_url = "https://openapi.naver.com/v1/search/shop.json"
        shop_headers = {
            "X-Naver-Client-Id": CLIENT_ID,
            "X-Naver-Client-Secret": CLIENT_SECRET
        }
        shop_params = {"query": rel_keyword, "display": 1}
        shop_resp = requests.get(shop_url, params=shop_params, headers=shop_headers)
        
        product_count = 0
        category = "오류/없음"
        
        if shop_resp.status_code == 200:
            shop_data = shop_resp.json()
            product_count = shop_data.get('total', 0)
            if product_count > 0 and shop_data.get('items'):
                item_info = shop_data['items'][0]
                categories = [
                    item_info.get('category1', ''),
                    item_info.get('category2', ''),
                    item_info.get('category3', ''),
                    item_info.get('category4', '')
                ]
                category = " > ".join([c for c in categories if c])
        elif shop_resp.status_code == 429:
            category = "차단됨(속도제한)"
            
        competition = round(product_count / total_vol, 2) if total_vol > 0 else 0
        conversion = round((total_vol / (product_count + 1)) * 100, 2)
        
        results.append({
            "연관키워드": rel_keyword,
            "쇼핑 카테고리": category,
            "월 검색량": total_vol,
            "상품수": product_count,
            "경쟁률": competition,
            "쇼핑전환(지수)": conversion
        })
        
        # 진행률 및 상태 텍스트 업데이트
        progress_bar.progress(idx / total_count)
        status_text.text(f"[{idx}/{total_count}] '{rel_keyword}' 분석 중...")
        
        time.sleep(0.12) 
        
    status_text.text("데이터 수집 완료!")
    return pd.DataFrame(results)

# ==========================================
# [웹페이지 UI 구성]
# ==========================================
st.set_page_config(page_title="키워드 분석기", layout="wide")

st.title("쇼핑 키워드 데이터 분석기")
st.write("키워드를 입력하면 연관키워드, 쇼핑카테고리, 월검색량, 상품수, 경쟁률, 쇼핑전환지수를 한눈에 보여줍니다.")

st.divider()

# 사용자 입력창
seed_keyword = st.text_input("분석할 기준 키워드를 입력하세요:", placeholder="예: 차량용방향제")

if st.button("데이터 분석 시작", type="primary"):
    if seed_keyword.strip() == "":
        st.warning("키워드를 입력해 주세요.")
    else:
        df = get_naver_keyword_data(seed_keyword)
        
        if df is not None and not df.empty:
            st.divider()
            st.subheader(f"'{seed_keyword}' 분석 결과")
            
            # 웹 화면에 데이터프레임 출력
            st.dataframe(df, use_container_width=True)
            
            # 엑셀 다운로드 기능 구현
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Keyword_Data')
            
            now_time = datetime.datetime.now().strftime("%y%m%d_%H%M")
            file_name = f"{seed_keyword}_분석리스트_{now_time}.xlsx"
            
            st.download_button(
                label="📥 엑셀 파일 다운로드",
                data=buffer.getvalue(),
                file_name=file_name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )