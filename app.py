# app.py 코드
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import pandas as pd
import streamlit as st
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from zoneinfo import ZoneInfo


st.set_page_config(
    page_title="유튜브 댓글 가져오기",
    page_icon="💬",
    layout="wide",
)


# 유튜브 주소에서 영상 아이디를 찾는 함수입니다.
def get_video_id(address: str) -> str | None:
    if not address:
        return None

    text = address.strip()

    # 주소가 아니라 영상 아이디만 넣은 경우도 처리합니다.
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", text):
        return text

    # 주소 앞에 https://가 빠진 경우도 처리합니다.
    if not text.startswith(("http://", "https://")):
        text = "https://" + text

    try:
        parsed = urlparse(text)
        host = parsed.netloc.lower()
        path = parsed.path.strip("/")
        query = parse_qs(parsed.query)

        # 일반 링크: https://www.youtube.com/watch?v=영상아이디
        if "youtube.com" in host and "v" in query:
            video_id = query.get("v", [""])[0]
            if re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id):
                return video_id

        # 짧은 링크: https://youtu.be/영상아이디
        if "youtu.be" in host:
            video_id = path.split("/")[0]
            if re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id):
                return video_id

        # shorts: https://www.youtube.com/shorts/영상아이디
        # embed: https://www.youtube.com/embed/영상아이디
        # live: https://www.youtube.com/live/영상아이디
        parts = path.split("/")
        for key in ["shorts", "embed", "live"]:
            if key in parts:
                index = parts.index(key)
                if len(parts) > index + 1:
                    video_id = parts[index + 1]
                    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id):
                        return video_id

        return None

    except Exception:
        return None


# 유튜브 연결을 한 번 만들면 다시 사용합니다.
@st.cache_resource
def get_youtube_client(api_key: str):
    return build("youtube", "v3", developerKey=api_key)


# UTC 시간을 한국 시간으로 바꿉니다.
def change_to_korea_time(utc_text: str) -> str:
    utc_time = datetime.fromisoformat(utc_text.replace("Z", "+00:00"))
    korea_time = utc_time.astimezone(ZoneInfo("Asia/Seoul"))
    return korea_time.strftime("%Y-%m-%d %H:%M:%S")


# 댓글을 가져오는 함수입니다.
def fetch_comments(youtube, video_id: str, max_comments: int) -> list[dict]:
    comments = []
    next_page_token = None

    while len(comments) < max_comments:
        request = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=min(100, max_comments - len(comments)),
            order="relevance",
            textFormat="plainText",
            pageToken=next_page_token,
        )

        response = request.execute()

        for item in response.get("items", []):
            snippet = item["snippet"]["topLevelComment"]["snippet"]

            comments.append(
                {
                    "댓글 내용": snippet.get("textDisplay", ""),
                    "작성 시각(한국시간)": change_to_korea_time(snippet.get("publishedAt", "")),
                    "좋아요 수": snippet.get("likeCount", 0),
                }
            )

        next_page_token = response.get("nextPageToken")

        if not next_page_token:
            break

    return comments


# 엑셀에서 한글이 깨지지 않도록 CSV 파일을 만듭니다.
def make_csv_for_excel(dataframe: pd.DataFrame) -> bytes:
    return dataframe.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


# API 키를 안전하게 읽습니다.
def read_api_key() -> str | None:
    try:
        key = st.secrets.get("youtube_api_key", "")
        if isinstance(key, str) and key.strip():
            return key.strip()
        return None
    except Exception:
        return None


st.title("유튜브 댓글 가져오기")
st.caption("주소를 넣고 버튼을 누르면 인기순 댓글을 표로 보여줍니다.")

api_key = read_api_key()

if not api_key:
    st.error("api키가 없어요. .streamlit/secrets.toml에 넣어주세요.")

video_address = st.text_input(
    "유튜브 주소",
    value="https://www.youtube.com/watch?v=WXuK6gekU1Y",
    placeholder="유튜브 영상 주소를 입력하세요.",
)

max_comments = st.number_input(
    "가져올 댓글 수",
    min_value=1,
    max_value=5000,
    value=300,
    step=100,
)

button_disabled = not bool(api_key)

clicked = st.button(
    "댓글 가져오기",
    type="primary",
    disabled=button_disabled,
)

if clicked:
    video_id = get_video_id(video_address)

    if not video_id:
        st.error("주소가 올바르지 않아요.")
        st.stop()

    try:
        youtube = get_youtube_client(api_key)

        with st.spinner("댓글을 가져오는 중입니다."):
            rows = fetch_comments(youtube, video_id, int(max_comments))

        if not rows:
            st.warning("가져온 댓글이 없어요.")
            st.stop()

        df = pd.DataFrame(rows)

        st.success(f"댓글 {len(df):,}개를 가져왔어요.")
        st.dataframe(df, use_container_width=True, hide_index=True)

        csv_data = make_csv_for_excel(df)

        st.download_button(
            label="CSV 내려받기",
            data=csv_data,
            file_name=f"youtube_comments_{video_id}.csv",
            mime="text/csv",
        )

    except HttpError as error:
        status = getattr(error.resp, "status", None)
        reason_text = ""

        try:
            reason_text = error.error_details[0].get("reason", "")
        except Exception:
            reason_text = str(error)

        reason_text_lower = reason_text.lower()
        error_text_lower = str(error).lower()

        if status == 403 and (
            "commentsdisabled" in reason_text_lower
            or "disabled comments" in error_text_lower
            or "comments disabled" in error_text_lower
        ):
            st.error("이 영상은 댓글을 볼 수 없어요.")

        elif status == 403 and (
            "quotaexceeded" in reason_text_lower
            or "dailyLimitExceeded" in str(error)
            or "quota" in error_text_lower
        ):
            st.error("오늘 사용할 수 있는 조회량이 다 됐어요.")

        else:
            st.error("댓글을 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")

    except Exception:
        st.error("댓글을 가져오는 중 문제가 생겼어요. 주소와 키를 다시 확인해 주세요.")
