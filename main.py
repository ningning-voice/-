import os
import re
import time
import requests
from bs4 import BeautifulSoup

# 1. 파일 저장 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "sent_combined_history.txt")

# 환경변수에서 가져오되, 노출 방지를 위해 기본값 토큰 삭제
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID = os.environ.get("CHAT_ID", "@wonhee_thief")

TOPIC_ID_REDDIT = int(os.environ.get("TOPIC_ID_REDDIT", "35"))
TOPIC_ID_DC = int(os.environ.get("TOPIC_ID_DC", "41"))

SUBREDDIT = os.environ.get("SUBREDDIT", "wonhee")
GALLERY_ID = os.environ.get("GALLERY_ID", "wonhee")

# 디시인사이드 차단 방지를 위한 Referer 및 User-Agent 설정
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://gall.dcinside.com/"
}

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        for post_id in history:
            f.write(f"{post_id}\n")

def send_telegram(title, link, img_url, source_tag="", topic_id=None):
    caption = f"🔥 [{source_tag}] {title}\n\n🔗 {link}"
    payload = {"chat_id": CHAT_ID}

    if topic_id:
        payload["message_thread_id"] = topic_id

    # 이미지 URL 존재 시 sendPhoto, 실패 시 sendMessage로 fallback
    if img_url:
        api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        payload["photo"] = img_url
        payload["caption"] = caption[:1000]
    else:
        api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload["text"] = caption[:4000]

    try:
        res = requests.post(api_url, data=payload, timeout=10)
        
        # 이미지 전송 실패(400 등) 시 텍스트만 재전송 시도
        if not res.ok and img_url:
            print(f"⚠️ [{source_tag}] 이미지 전송 실패 ({res.status_code}), 텍스트로 재시도합니다.")
            api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {"chat_id": CHAT_ID, "text": caption[:4000]}
            if topic_id:
                payload["message_thread_id"] = topic_id
            res = requests.post(api_url, data=payload, timeout=10)

        return res.ok
    except Exception as e:
        print(f"❌ 텔레그램 전송 에러: {e}")
        return False

def get_reddit_posts(limit=15):
    """최신 레딧 게시글 수집 (hot.rss -> new.rss 변경)"""
    url = f"https://www.reddit.com/r/{SUBREDDIT}/new.rss"

    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            print(f"[Reddit] 접속 실패: Status Code {res.status_code}")
            return []

        soup = BeautifulSoup(res.text, "xml")  # RSS 파싱을 위해 xml 파서 사용
        entries = soup.find_all("entry")[:limit]

        posts = []
        for entry in entries:
            post_id_el = entry.find("id")
            raw_id = post_id_el.text if post_id_el else ""
            post_id = f"reddit_{raw_id}"

            title_el = entry.find("title")
            title = title_el.text if title_el else ""

            link_tag = entry.find("link")
            link = link_tag["href"] if link_tag and link_tag.has_attr("href") else ""

            content_el = entry.find("content")
            content = content_el.text if content_el else ""

            # 다양한 이미지 URL 패턴 감지 (.jpeg, 쿼리스트링 포함 대응)
            img_match = re.search(r'href="(https://i\.redd\.it/[^"]+)"', content)
            if not img_match:
                img_match = re.search(r'src="(https://preview\.redd\.it/[^"]+)"', content)

            img_url = img_match.group(1) if img_match else None
            if img_url:
                img_url = img_url.replace("&amp;", "&")

            posts.append({
                "id": post_id,
                "title": title,
                "link": link,
                "img_url": img_url,
                "source": f"r/{SUBREDDIT}",
                "topic_id": TOPIC_ID_REDDIT,
            })

        return posts
    except Exception as e:
        print(f"[Reddit] 파싱 에러: {e}")
        return []

def get_dc_detail(post_url):
    """디시인사이드 개별 글 이미지 파싱 (절대경로 변환 및 Referer 적용)"""
    try:
        res = requests.get(post_url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            print(f"[DC Detail] 글 접근 실패 ({res.status_code}): {post_url}")
            return None
        
        soup = BeautifulSoup(res.text, "html.parser")
        
        # 본문 영역 탐색 (.write_div 또는 .thum-txtin)
        write_div = soup.select_one(".write_div") or soup.select_one(".thum-txtin")
        if not write_div:
            return None

        img_tag = write_div.select_one("img")
        if img_tag and img_tag.has_attr("src"):
            src = img_tag["src"]
            # 프로토콜 상대 경로(//image...) 처리 및 절대 경로 변환
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = "https://gall.dcinside.com" + src
            return src

        return None
    except Exception as e:
        print(f"[DC Detail] 에러 발생 ({post_url}): {e}")
        return None

def get_dc_posts(limit=15):
    """최신 디시 개념글 수집"""
    url = f"https://gall.dcinside.com/mgallery/board/lists/?id={GALLERY_ID}&exception_mode=recommend"

    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            print(f"[DC] 접속 실패: Status Code {res.status_code}")
            return []

        soup = BeautifulSoup(res.text, "html.parser")
        rows = soup.select("tr.ub-content.us-post")

        posts = []
        for row in rows:
            if len(posts) >= limit:
                break

            gall_num_el = row.select_one(".gall_num")
            if not gall_num_el or not gall_num_el.text.strip().isdigit():
                continue

            raw_id = gall_num_el.text.strip()
            post_id = f"dc_{raw_id}"

            title_el = row.select_one(".gall_tit a")
            if not title_el:
                continue

            title = title_el.text.strip()
            href = title_el["href"]
            link = "https://gall.dcinside.com" + href if href.startswith("/") else href

            posts.append({
                "id": post_id,
                "title": title,
                "link": link,
                "source": f"DC {GALLERY_ID}",
                "topic_id": TOPIC_ID_DC,
            })

        return posts
    except Exception as e:
        print(f"[DC] 파싱 에러: {e}")
        return []

def main():
    print(f"📌 히스토리 파일 저장 위치: {HISTORY_FILE}")

    history = load_history()

    # 수집 한도 증가 (10 -> 15개)
    reddit_posts = get_reddit_posts(limit=15)
    dc_posts = get_dc_posts(limit=15)

    print(f"수집 완료 -> Reddit: {len(reddit_posts)}개, DC: {len(dc_posts)}개")

    combined_posts = []
    max_len = max(len(reddit_posts), len(dc_posts))
    for i in range(max_len):
        if i < len(dc_posts):
            combined_posts.append(dc_posts[i])
        if i < len(reddit_posts):
            combined_posts.append(reddit_posts[i])

    # 예전 글부터 순서대로 전송
    for post in reversed(combined_posts):
        post_id = post["id"]

        if post_id in history:
            continue

        img_url = post.get("img_url")
        if post_id.startswith("dc_"):
            img_url = get_dc_detail(post["link"])
            time.sleep(0.5)  # 디시 차단 방지를 위한 짧은 딜레이

        if send_telegram(
            post["title"],
            post["link"],
            img_url,
            post["source"],
            post.get("topic_id"),
        ):
            print(f"[성공] [{post['source']}] {post['title']}")
            history.add(post_id)

    save_history(history)

if __name__ == "__main__":
    main()
