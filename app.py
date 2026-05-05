# app.py 코드
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import pandas as pd
import requests
import streamlit as st
from zoneinfo import ZoneInfo


st.set_page_config(
    page_title="유튜브 댓글 가져오기",
    page_icon="💬",
    layout="wide",
)


기본_주소 = "https://www.youtube.com/watch?v=WXuK6gekU1Y"


# 유튜브 API 주소입니다.
댓글_API_주소 = "https://www.googleapis.com/youtube/v3/commentThreads"


# 유튜브 영상 아이디는 보통 11글자입니다.
영상_ID_규칙 = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def 비밀키_읽기():
    """Streamlit 비밀키에서 유튜브 API 키를 읽습니다."""
    try:
        api_key = st.secrets.get("youtube_api_key", "")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
        return None
    except Exception:
        return None


def 영상_id_찾기(주소):
    """일반 링크, 짧은 링크, shorts, embed, live 주소에서 영상 아이디를 찾습니다."""
    if not 주소:
        return None

    주소 = 주소.strip()

    # 영상 아이디만 바로 넣은 경우
    if 영상_ID_규칙.fullmatch(주소):
        return 주소

    # https:// 없이 입력한 경우도 처리합니다.
    if not 주소.startswith(("http://", "https://")):
        주소 = "https://" + 주소

    try:
        파싱 = urlparse(주소)
        도메인 = 파싱.netloc.lower()
        경로 = 파싱.path.strip("/")
        쿼리 = parse_qs(파싱.query)

        # 일반 주소: youtube.com/watch?v=영상아이디
        if "youtube.com" in 도메인 and "v" in 쿼리:
            영상_id = 쿼리.get("v", [""])[0]
            if 영상_ID_규칙.fullmatch(영상_id):
                return 영상_id

        # 짧은 주소: youtu.be/영상아이디
        if "youtu.be" in 도메인:
            영상_id = 경로.split("/")[0]
            if 영상_ID_규칙.fullmatch(영상_id):
                return 영상_id

        # shorts/embed/live 주소 처리
        경로_조각들 = 경로.split("/")
        가능한_형태 = ["shorts", "embed", "live", "v"]

        for 형태 in 가능한_형태:
            if 형태 in 경로_조각들:
                위치 = 경로_조각들.index(형태)
                if len(경로_조각들) > 위치 + 1:
                    영상_id = 경로_조각들[위치 + 1]
                    if 영상_ID_규칙.fullmatch(영상_id):
                        return 영상_id

        return None

    except Exception:
        return None


def 한국시간으로_바꾸기(utc_시간문자):
    """UTC 시간을 한국 시간으로 바꿉니다."""
    try:
        utc_시간 = datetime.fromisoformat(utc_시간문자.replace("Z", "+00:00"))
        한국_시간 = utc_시간.astimezone(ZoneInfo("Asia/Seoul"))
        return 한국_시간.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


@st.cache_resource
def 유튜브_연결_만들기():
    """유튜브 API 호출에 사용할 연결을 한 번만 만듭니다."""
    연결 = requests.Session()
    연결.headers.update({"Accept": "application/json"})
    return 연결


def 오류_메시지_고르기(응답):
    """유튜브 API 오류를 쉬운 문장으로 바꿉니다."""
    상태코드 = 응답.status_code

    try:
        오류정보 = 응답.json()
    except Exception:
        오류정보 = {}

    오류목록 = 오류정보.get("error", {}).get("errors", [])
    오류사유 = ""

    if 오류목록 and isinstance(오류목록, list):
        오류사유 = 오류목록[0].get("reason", "")

    오류사유_소문자 = 오류사유.lower()
    응답내용_소문자 = 응답.text.lower()

    if 상태코드 == 403 and (
        "commentsdisabled" in 오류사유_소문자
        or "comments disabled" in 응답내용_소문자
        or "disabled comments" in 응답내용_소문자
    ):
        return "이 영상은 댓글을 볼수 없어요."

    if 상태코드 == 403 and (
        "quotaexceeded" in 오류사유_소문자
        or "dailylimitexceeded" in 오류사유_소문자
        or "quota" in 응답내용_소문자
    ):
        return "오늘 사용할 수 있는 조회량이 다 됐어요."

    return "댓글을 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요."


def 댓글_가져오기(api_key, 영상_id, 가져올_개수):
    """유튜브 댓글을 인기순으로 가져옵니다."""
    연결 = 유튜브_연결_만들기()

    댓글목록 = []
    다음페이지 = None

    while len(댓글목록) < 가져올_개수:
        한번에_가져올_개수 = min(100, 가져올_개수 - len(댓글목록))

        요청값 = {
            "key": api_key,
            "part": "snippet",
            "videoId": 영상_id,
            "maxResults": 한번에_가져올_개수,
            "order": "relevance",
            "textFormat": "plainText",
        }

        if 다음페이지:
            요청값["pageToken"] = 다음페이지

        응답 = 연결.get(댓글_API_주소, params=요청값, timeout=20)

        if not 응답.ok:
            raise RuntimeError(오류_메시지_고르기(응답))

        데이터 = 응답.json()

        for 항목 in 데이터.get("items", []):
            try:
                댓글정보 = 항목["snippet"]["topLevelComment"]["snippet"]

                댓글목록.append(
                    {
                        "댓글 내용": 댓글정보.get("textDisplay", ""),
                        "작성 시각(한국시간)": 한국시간으로_바꾸기(댓글정보.get("publishedAt", "")),
                        "좋아요 수": 댓글정보.get("likeCount", 0),
                    }
                )
            except Exception:
                continue

        다음페이지 = 데이터.get("nextPageToken")

        if not 다음페이지:
            break

    return 댓글목록


def 엑셀용_csv_만들기(표):
    """엑셀에서 한글이 깨지지 않도록 CSV 파일을 만듭니다."""
    return 표.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


st.title("유튜브 댓글 가져오기")
st.caption("유튜브 주소를 입력하면 인기순 댓글을 표로 보여주고 CSV로 저장할 수 있습니다.")

api_key = 비밀키_읽기()

if not api_key:
    st.error("api키가 없어요. .streamlit/secrets.toml에 넣어주세요")

주소 = st.text_input(
    "유튜브 주소",
    value=기본_주소,
    placeholder="유튜브 영상 주소를 입력하세요.",
)

가져올_개수 = st.number_input(
    "가져올 댓글 수",
    min_value=1,
    max_value=5000,
    value=300,
    step=100,
)

버튼눌림 = st.button(
    "댓글 가져오기",
    type="primary",
    disabled=api_key is None,
)

if 버튼눌림:
    영상_id = 영상_id_찾기(주소)

    if not 영상_id:
        st.error("주소가 올바르지 않아요.")
        st.stop()

    try:
        with st.spinner("댓글을 가져오는 중입니다."):
            댓글목록 = 댓글_가져오기(
                api_key=api_key,
                영상_id=영상_id,
                가져올_개수=int(가져올_개수),
            )

        if not 댓글목록:
            st.warning("가져온 댓글이 없어요.")
            st.stop()

        표 = pd.DataFrame(댓글목록)

        st.success(f"댓글 {len(표):,}개를 가져왔어요.")
        st.dataframe(
            표,
            use_container_width=True,
            hide_index=True,
        )

        csv_파일 = 엑셀용_csv_만들기(표)

        st.download_button(
            label="CSV 내려받기",
            data=csv_파일,
            file_name=f"youtube_comments_{영상_id}.csv",
            mime="text/csv",
        )

    except RuntimeError as 오류:
        st.error(str(오류))

    except requests.exceptions.Timeout:
        st.error("댓글을 가져오는 중 문제가 생겼어요. 유튜브 연결 시간이 너무 오래 걸렸어요.")

    except requests.exceptions.RequestException:
        st.error("댓글을 가져오는 중 문제가 생겼어요. 인터넷 연결을 다시 확인해 주세요.")

    except Exception:
        st.error("댓글을 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
