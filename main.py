import os
import re
import time
import requests
from bs4 import BeautifulSoup

# ============================================================
# GitHub Actions용 Reddit + DC 크롤러
# - 실행 후 작업을 끝내고 종료한다.
# - Telegram polling을 하지 않는다.
# - 30분마다 GitHub Actions가 이 파일을 실행하는 구조에 맞춰져 있다.
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "sent_combined_history.txt")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "@wonhee_thief")

TOPIC_ID_REDDIT = int(os.environ.get("TOPIC_ID_REDDIT", "35"))
TOPIC_ID_DC = int(os.environ.get("TOPIC_ID_DC", "41"))

SUBREDDIT = os.environ.get("SUBREDDIT", "wonhee+minju_+minjupark+Illit_Hotties")
GALLERY_ID = os.environ.get("GALLERY_ID", "wonhee")

# Reddit은 RSS에서 한 번에 많이 가져오기 어렵기 때문에
# 기존처럼 20개만 가져온다.
REDDIT_LIMIT = int(os.environ.get("REDDIT_LIMIT", "20"))
DC_LIMIT = int(os.environ.get("DC_LIMIT", "100"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/143.0.0.0 Safari/537.36"
    ),
    "Referer": "https://gall.dcinside.com/",
}


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return set()

    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def save_history(history):
    # 집합을 다시 파일로 저장. 정렬해서 diff가 안정적으로 보이게 한다.
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        for post_id in sorted(history):
            f.write(post_id + "\n")


def send_telegram(title, link, img_url=None, source_tag="", topic_id=None):
    caption = f"🔥 [{source_tag}] {title}\n\n🔗 {link}"

    if img_url:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": CHAT_ID,
            "photo": img_url,
            "caption": caption[:1024],
        }
    else:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": caption[:4096],
        }

    if topic_id:
        payload["message_thread_id"] = topic_id

    try:
        response = requests.post(url, data=payload, timeout=20)

        # Telegram이 외부 이미지 URL을 직접 가져오지 못할 때 텍스트라도 보낸다.
        if not response.ok and img_url:
            print(
                f"⚠️ 이미지 전송 실패: "
                f"{response.status_code} {response.text[:250]}"
            )
            fallback = {
                "chat_id": CHAT_ID,
                "text": caption[:4096],
            }
            if topic_id:
                fallback["message_thread_id"] = topic_id

            response = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data=fallback,
                timeout=20,
            )

        if not response.ok:
            print(
                f"❌ Telegram 전송 실패: "
                f"{response.status_code} {response.text[:400]}"
            )

        return response.ok

    except Exception as e:
        print(f"❌ Telegram 요청 에러: {e}")
        return False


# ============================================================
# Reddit
# ============================================================

def get_reddit_posts(limit=20):
    url = f"https://www.reddit.com/r/{SUBREDDIT}/new.rss"

    try:
        response = requests.get(url, headers=HEADERS, timeout=20)

        if response.status_code != 200:
            print(f"[Reddit] RSS 접속 실패: {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, "xml")
        entries = soup.find_all("entry")[:limit]

        posts = []

        for entry in entries:
            id_element = entry.find("id")
            raw_id = id_element.get_text(strip=True) if id_element else ""
            if not raw_id:
                continue

            title_element = entry.find("title")
            title = title_element.get_text(strip=True) if title_element else "(제목 없음)"

            link_element = entry.find("link")
            link = (
                link_element.get("href", "")
                if link_element
                else ""
            )
            if not link:
                continue

            content_element = entry.find("content")
            content = content_element.get_text() if content_element else ""

            img_url = None

            # RSS 안에 원본 이미지가 들어오는 경우
            match = re.search(
                r'href="(https://i\.redd\.it/[^"]+)"',
                content,
                re.IGNORECASE,
            )
            if not match:
                match = re.search(
                    r'src="(https://preview\.redd\.it/[^"]+)"',
                    content,
                    re.IGNORECASE,
                )

            if match:
                img_url = match.group(1).replace("&amp;", "&")

            posts.append({
                "id": f"reddit_{raw_id}",
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


# ============================================================
# DCInside
# ============================================================

def get_dc_detail(post_url):
    try:
        response = requests.get(post_url, headers=HEADERS, timeout=20)

        if response.status_code != 200:
            print(f"[DC Detail] 접근 실패: {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        write_div = (
            soup.select_one(".write_div")
            or soup.select_one(".thum-txtin")
        )
        if not write_div:
            return None

        img = write_div.select_one("img")
        if not img:
            return None

        src = img.get("src")
        if not src:
            return None

        if src.startswith("//"):
            return "https:" + src
        if src.startswith("/"):
            return "https://gall.dcinside.com" + src

        return src

    except Exception as e:
        print(f"[DC Detail] 에러: {e}")
        return None


def get_dc_posts(limit=100):
    url = (
        "https://gall.dcinside.com/mgallery/board/lists/"
        f"?id={GALLERY_ID}&exception_mode=recommend"
    )

    try:
        response = requests.get(url, headers=HEADERS, timeout=20)

        if response.status_code != 200:
            print(f"[DC] 접속 실패: {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.select("tr.ub-content.us-post")

        posts = []

        for row in rows:
            if len(posts) >= limit:
                break

            number = row.select_one(".gall_num")
            if not number:
                continue

            raw_id = number.get_text(strip=True)
            if not raw_id.isdigit():
                continue

            title_element = row.select_one(".gall_tit a")
            if not title_element:
                continue

            title = title_element.get_text(strip=True)
            href = title_element.get("href", "")
            if not href:
                continue

            link = (
                "https://gall.dcinside.com" + href
                if href.startswith("/")
                else href
            )

            posts.append({
                "id": f"dc_{raw_id}",
                "title": title,
                "link": link,
                "source": f"DC {GALLERY_ID}",
                "topic_id": TOPIC_ID_DC,
            })

        return posts

    except Exception as e:
        print(f"[DC] 파싱 에러: {e}")
        return []


# ============================================================
# 실행
# ============================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN 환경변수가 없습니다.")

    history = load_history()

    reddit_posts = get_reddit_posts(REDDIT_LIMIT)
    dc_posts = get_dc_posts(DC_LIMIT)

    print(
        f"수집 완료 -> Reddit {len(reddit_posts)}개 / "
        f"DC {len(dc_posts)}개"
    )

    combined = []
    max_len = max(len(reddit_posts), len(dc_posts))

    # 기존처럼 DC와 Reddit을 교차 배치
    for i in range(max_len):
        if i < len(dc_posts):
            combined.append(dc_posts[i])
        if i < len(reddit_posts):
            combined.append(reddit_posts[i])

    # 새 글이 먼저 들어온 RSS/list와 실제 게시 시점을 고려해
    # 기존과 동일하게 역순 전송한다.
    for post in reversed(combined):
        if post["id"] in history:
            continue

        img_url = post.get("img_url")

        if post["id"].startswith("dc_"):
            img_url = get_dc_detail(post["link"])
            time.sleep(0.5)

        if send_telegram(
            post["title"],
            post["link"],
            img_url,
            post["source"],
            post["topic_id"],
        ):
            history.add(post["id"])
            print(f"[성공] [{post['source']}] {post['title']}")

    save_history(history)


if __name__ == "__main__":
    main()
