import os
import re
import requests
from bs4 import BeautifulSoup

# 1. 깃허브 서버 및 로컬 공통 절대 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "sent_combined_history.txt")

# 2. GitHub Secrets 환경변수 불러오기 (보안)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
TOPIC_ID_REDDIT = int(os.environ.get("TOPIC_ID_REDDIT", "35"))
TOPIC_ID_DC = int(os.environ.get("TOPIC_ID_DC", "41"))
SUBREDDIT = os.environ.get("SUBREDDIT", "wonhee")
GALLERY_ID = os.environ.get("GALLERY_ID", "wonhee")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
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

    if img_url:
        api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        payload["photo"] = img_url
        payload["caption"] = caption[:1000]
    else:
        api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload["text"] = caption[:4000]

    try:
        res = requests.post(api_url, data=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print(f"텔레그램 전송 에러: {e}")
        return False


def get_reddit_posts(limit=5):
    """최신 레딧 게시글 최대 limit개 수집"""
    url = f"https://www.reddit.com/r/{SUBREDDIT}/hot.rss"

    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            print(f"[Reddit] 접속 실패: Status Code {res.status_code}")
            return []

        soup = BeautifulSoup(res.text, "html.parser")
        entries = soup.find_all("entry")[:limit]  # 상위 limit개만 잘라냄

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

            img_match = re.search(
                r'href="(https://i\.redd\.it/[^"]+\.(?:jpg|png|gif))"', content
            )
            if not img_match:
                img_match = re.search(
                    r'src="(https://preview\.redd\.it/[^"]+\.(?:jpg|png|gif)[^"]*)"',
                    content,
                )

            img_url = img_match.group(1) if img_match else None

            posts.append(
                {
                    "id": post_id,
                    "title": title,
                    "link": link,
                    "img_url": img_url,
                    "source": f"r/{SUBREDDIT}",
                    "topic_id": TOPIC_ID_REDDIT,
                }
            )

        return posts
    except Exception as e:
        print(f"[Reddit] 파싱 에러: {e}")
        return []


def get_dc_detail(post_url):
    try:
        res = requests.get(post_url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return None
        soup = BeautifulSoup(res.text, "html.parser")
        write_div = soup.select_one(".write_div")
        if not write_div:
            return None
        img_tag = write_div.select_one("img")
        return img_tag["src"] if img_tag and img_tag.has_attr("src") else None
    except Exception:
        return None


def get_dc_posts(limit=5):
    """최신 디시 개념글 최대 limit개 수집"""
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
            if len(posts) >= limit:  # limit개 채워지면 중단
                break

            gall_num_el = row.select_one(".gall_num")
            if not gall_num_el or not gall_num_el.text.strip().isdigit():
                continue

            raw_id = gall_num_el.text.strip()
            post_id = f"dc_{raw_id}"

            title_el = row.select_one(".gall_tit a")
            title = title_el.text.strip()

            href = title_el["href"]
            link = "https://gall.dcinside.com" + href if href.startswith("/") else href

            posts.append(
                {
                    "id": post_id,
                    "title": title,
                    "link": link,
                    "source": f"DC {GALLERY_ID}",
                    "topic_id": TOPIC_ID_DC,
                }
            )

        return posts
    except Exception as e:
        print(f"[DC] 파싱 에러: {e}")
        return []


def main():
    print(f"📌 히스토리 파일 저장 위치: {HISTORY_FILE}")

    history = load_history()

    # 각각 최신글 5개씩 수집
    reddit_posts = get_reddit_posts(limit=10)
    dc_posts = get_dc_posts(limit=10)

    print(f"수집 완료 -> Reddit: {len(reddit_posts)}개, DC: {len(dc_posts)}개")

    # 교대로 교차 배치 (디시 1개 -> 레딧 1개 -> 디시 1개...)
    combined_posts = []
    max_len = max(len(reddit_posts), len(dc_posts))
    for i in range(max_len):
        if i < len(dc_posts):
            combined_posts.append(dc_posts[i])
        if i < len(reddit_posts):
            combined_posts.append(reddit_posts[i])

    # 예전 글부터 순서대로 보낼 수 있도록 역순 정렬
    for post in reversed(combined_posts):
        post_id = post["id"]

        if post_id in history:
            continue

        img_url = post.get("img_url")
        if post_id.startswith("dc_"):
            img_url = get_dc_detail(post["link"])

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
