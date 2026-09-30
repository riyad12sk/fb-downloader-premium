from flask import Flask, request, jsonify, render_template_string, send_file
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import os
import uuid
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp


# =========================================================
# APP CONFIG
# =========================================================

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["500 per day", "100 per hour"],
    storage_uri="memory://"
)

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Cookies file path (Ensure cookies.txt is uploaded in GitHub root)
COOKIE_FILE = BASE_DIR / "cookies.txt"

MAX_FILE_SIZE = 500 * 1024 * 1024
MAX_FILE_AGE = 30 * 60
CLEANUP_INTERVAL = 10 * 60


# =========================================================
# CLEANUP
# =========================================================

def cleanup_old_files():
    while True:
        try:
            now = time.time()

            if DOWNLOAD_DIR.exists():
                for item in DOWNLOAD_DIR.iterdir():
                    try:
                        if item.is_dir():
                            age = now - item.stat().st_mtime

                            if age > MAX_FILE_AGE:
                                shutil.rmtree(item, ignore_errors=True)

                        elif item.is_file():
                            age = now - item.stat().st_mtime

                            if age > MAX_FILE_AGE:
                                item.unlink(missing_ok=True)

                    except Exception:
                        pass

        except Exception:
            pass

        time.sleep(CLEANUP_INTERVAL)


threading.Thread(
    target=cleanup_old_files,
    daemon=True
).start()


# =========================================================
# HELPERS
# =========================================================

def is_supported_url(url):
    try:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return False

        host = (parsed.hostname or "").lower()

        supported = (
            "youtube.com",
            "youtu.be",
            "facebook.com",
            "fb.watch",
            "tiktok.com",
            "vm.tiktok.com",
            "vt.tiktok.com"
        )

        return any(
            host == domain or host.endswith("." + domain)
            for domain in supported
        )

    except Exception:
        return False


def clean_error(error):
    text = str(error).strip()

    if not text:
        return "Download failed."

    if "Requested format is not available" in text:
        return (
            "The selected quality is not available for this video. "
            "Please try another quality."
        )

    if "Cannot parse data" in text:
        return (
            "Facebook could not provide this public video to the "
            "downloader. Please try another public Facebook video."
        )

    if "Private" in text or "login" in text.lower():
        return (
            "This video appears to require login or is not publicly "
            "accessible."
        )

    if "Unsupported URL" in text:
        return "This URL is not supported."

    if "Sign in" in text:
        return (
            "This video requires login and cannot be downloaded "
            "through public access."
        )

    return text[-1200:]


# =========================================================
# HOME PAGE
# =========================================================

HTML = r"""
<!DOCTYPE html>
<html lang="en">

<head>
<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width,
      initial-scale=1.0,
      maximum-scale=1.0,
      user-scalable=no">

<title>BLACK CAT - All Video Downloader</title>

<style>

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    min-height: 100vh;
    font-family: Arial, Helvetica, sans-serif;
    color: #fff;
    background:
        radial-gradient(circle at 20% 20%, #24104d 0%, transparent 35%),
        radial-gradient(circle at 80% 80%, #073b4c 0%, transparent 35%),
        #050509;
    overflow-x: hidden;
}

.bg {
    position: fixed;
    inset: 0;
    pointer-events: none;
    overflow: hidden;
    z-index: 0;
}

.orb {
    position: absolute;
    width: 220px;
    height: 220px;
    border-radius: 50%;
    filter: blur(60px);
    opacity: .35;
    animation: move 12s infinite alternate ease-in-out;
}

.orb.one {
    background: #ff00aa;
    top: 5%;
    left: -50px;
}

.orb.two {
    background: #00e5ff;
    right: -50px;
    bottom: 10%;
    animation-delay: 3s;
}

.orb.three {
    background: #7c00ff;
    left: 35%;
    bottom: -100px;
    animation-delay: 6s;
}

@keyframes move {
    from {
        transform: translate(0, 0) scale(1);
    }

    to {
        transform: translate(80px, -60px) scale(1.3);
    }
}

.container {
    position: relative;
    z-index: 1;
    width: min(92%, 700px);
    margin: auto;
    padding: 35px 0 50px;
}

.logo {
    text-align: center;
    font-size: clamp(38px, 12vw, 72px);
    font-weight: 900;
    letter-spacing: 5px;
    margin-top: 15px;

    background: linear-gradient(
        90deg,
        #ff006e,
        #ffbe0b,
        #00f5d4,
        #00bbf9,
        #9b5de5,
        #ff006e
    );

    background-size: 400% auto;
    color: transparent;
    background-clip: text;
    -webkit-background-clip: text;

    animation: rainbow 6s linear infinite;
}

@keyframes rainbow {
    to {
        background-position: 400% center;
    }
}

.subtitle {
    text-align: center;
    margin-top: 5px;
    color: #bbb;
    font-size: 14px;
    letter-spacing: 2px;
}

.creator {
    text-align: center;
    margin-top: 10px;
    color: #777;
    font-size: 12px;
}

.card {
    margin-top: 30px;
    padding: 22px;
    border: 1px solid rgba(255,255,255,.12);
    border-radius: 22px;
    background: rgba(255,255,255,.06);
    backdrop-filter: blur(18px);
    box-shadow:
        0 20px 60px rgba(0,0,0,.45),
        inset 0 1px rgba(255,255,255,.08);
}

.label {
    display: block;
    margin-bottom: 10px;
    color: #ddd;
    font-size: 14px;
    font-weight: bold;
}

.url-box {
    position: relative;
    display: flex;
    align-items: center;
}

.url-input {
    width: 100%;
    padding: 16px;
    padding-right: 45px;
    border-radius: 14px;
    border: 1px solid rgba(255,255,255,.15);
    outline: none;
    background: rgba(0,0,0,.4);
    color: #fff;
    font-size: 15px;
}

.url-input:focus {
    border-color: #00e5ff;
    box-shadow: 0 0 20px rgba(0,229,255,.15);
}

.clear-btn {
    position: absolute;
    right: 15px;
    background: none;
    border: none;
    color: #aaa;
    font-size: 20px;
    cursor: pointer;
    display: none;
    padding: 5px;
}

.clear-btn:hover {
    color: #fff;
}

.quality-title {
    margin-top: 22px;
    margin-bottom: 10px;
    color: #ddd;
    font-size: 14px;
    font-weight: bold;
}

.quality {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
}

.quality button {
    padding: 13px 8px;
    border: 1px solid rgba(255,255,255,.15);
    border-radius: 12px;
    background: rgba(255,255,255,.07);
    color: #fff;
    font-weight: bold;
    cursor: pointer;
}

.quality button.active {
    background: linear-gradient(135deg, #00b4db, #0083b0);
    border-color: #00e5ff;
    box-shadow: 0 0 20px rgba(0,229,255,.25);
}

.download-btn {
    width: 100%;
    margin-top: 22px;
    padding: 16px;
    border: 0;
    border-radius: 15px;
    background: linear-gradient(135deg, #00e5ff, #0077ff);
    color: #fff;
    font-size: 17px;
    font-weight: 900;
    cursor: pointer;
    box-shadow: 0 10px 30px rgba(0,140,255,.25);
}

.download-btn:disabled {
    opacity: .5;
    cursor: not-allowed;
}

.status {
    display: none;
    margin-top: 18px;
    padding: 15px;
    border-radius: 14px;
    background: rgba(0,0,0,.35);
    border: 1px solid rgba(255,255,255,.1);
    line-height: 1.5;
    font-size: 14px;
    word-break: break-word;
}

.result {
    display: none;
    margin-top: 18px;
    padding: 18px;
    border-radius: 16px;
    background: rgba(0,255,150,.07);
    border: 1px solid rgba(0,255,150,.2);
}

.result-title {
    font-size: 14px;
    color: #ddd;
    line-height: 1.5;
    word-break: break-word;
}

.ready-btn {
    display: block;
    margin-top: 14px;
    padding: 14px;
    text-align: center;
    text-decoration: none;
    border-radius: 13px;
    background: #00c853;
    color: #fff;
    font-weight: bold;
}

.telegram {
    display: block;
    margin-top: 20px;
    text-align: center;
    color: #55c7ff;
    text-decoration: none;
    font-size: 14px;
}

.footer {
    text-align: center;
    margin-top: 25px;
    color: #555;
    font-size: 11px;
}

</style>
</head>

<body>

<div class="bg">
    <div class="orb one"></div>
    <div class="orb two"></div>
    <div class="orb three"></div>
</div>

<div class="container">

    <div class="logo">BLACK CAT</div>

    <div class="subtitle">
        ALL VIDEO DOWNLOADER
    </div>

    <div class="creator">
        MODIFY BY SK SHORIF HASAN
    </div>

    <div class="card">

        <label class="label">
            Video URL
        </label>

        <div class="url-box">
            <input
                id="url"
                class="url-input"
                type="url"
                placeholder="Paste YouTube, Facebook or TikTok URL"
                autocomplete="off"
            >
            <button type="button" id="clearBtn" class="clear-btn">&times;</button>
        </div>

        <div class="quality-title">
            Select Quality
        </div>

        <div class="quality">

            <button
                class="quality-btn active"
                data-quality="480">
                480P
            </button>

            <button
                class="quality-btn"
                data-quality="720">
                720P
            </button>

            <button
                class="quality-btn"
                data-quality="1080">
                1080P
            </button>

        </div>

        <button
            id="downloadBtn"
            class="download-btn">
            DOWNLOAD VIDEO
        </button>

        <div id="status" class="status"></div>

        <div id="result" class="result">

            <div class="result-title">
                <b>Video ready:</b>
                <span id="videoTitle"></span>
            </div>

            <a
                id="readyBtn"
                class="ready-btn"
                href="#"
                download>
                DOWNLOAD FILE
            </a>

        </div>

        <a
            class="telegram"
            href="https://t.me/sk_black_cat"
            target="_blank">
            Join BLACK CAT on Telegram
        </a>

    </div>

    <div class="footer">
        BLACK CAT © 2026
    </div>

</div>

<script>

let selectedQuality = "480";

const qualityButtons =
    document.querySelectorAll(".quality-btn");

const urlInput =
    document.getElementById("url");

const clearBtn =
    document.getElementById("clearBtn");

const downloadBtn =
    document.getElementById("downloadBtn");

const statusBox =
    document.getElementById("status");

const resultBox =
    document.getElementById("result");

const videoTitle =
    document.getElementById("videoTitle");

const readyBtn =
    document.getElementById("readyBtn");


urlInput.addEventListener("input", () => {
    if (urlInput.value.trim() !== "") {
        clearBtn.style.display = "block";
    } else {
        clearBtn.style.display = "none";
    }
});


clearBtn.addEventListener("click", () => {
    urlInput.value = "";
    clearBtn.style.display = "none";
    urlInput.focus();
});


qualityButtons.forEach(button => {

    button.addEventListener("click", () => {

        qualityButtons.forEach(btn =>
            btn.classList.remove("active")
        );

        button.classList.add("active");

        selectedQuality =
            button.dataset.quality;

    });

});


function showStatus(message) {

    statusBox.style.display = "block";

    statusBox.textContent = message;

}


downloadBtn.addEventListener("click", async () => {

    const url = urlInput.value.trim();

    resultBox.style.display = "none";

    if (!url) {

        showStatus(
            "Please paste a video URL first."
        );

        return;
    }

    downloadBtn.disabled = true;

    showStatus(
        "Processing video... Please wait."
    );

    try {

        const response = await fetch(
            "/download",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({
                    url: url,
                    quality: selectedQuality
                })
            }
        );

        const contentType =
            response.headers.get(
                "content-type"
            ) || "";

        let data;

        if (contentType.includes("application/json")) {

            data = await response.json();

        } else {

            const text =
                await response.text();

            throw new Error(
                "Server returned an unexpected response."
            );
        }

        if (!data.success) {

            throw new Error(
                data.error ||
                "Download failed."
            );
        }

        videoTitle.textContent =
            data.title || "Video";

        readyBtn.href =
            data.download_url;

        resultBox.style.display =
            "block";

        showStatus(
            "Video is ready."
        );

    } catch (error) {

        showStatus(
            error.message ||
            "Download failed."
        );

    } finally {

        downloadBtn.disabled = false;

    }

});

</script>

</body>
</html>
"""


# =========================================================
# ROUTES
# =========================================================

@app.route("/")
def home():
    return render_template_string(HTML)


@app.route("/ping")
@limiter.exempt
def ping():
    return "Alive", 200


@app.route("/download", methods=["POST"])
@limiter.limit("5 per minute")
def download_video():

    data = request.get_json(silent=True) or {}

    video_url = str(
        data.get("url", "")
    ).strip()

    requested_quality = str(
        data.get("quality", "480")
    ).strip()

    if not video_url:
        return jsonify(
            success=False,
            error="Video URL is required."
        ), 400

    if not is_supported_url(video_url):
        return jsonify(
            success=False,
            error=(
                "Only public YouTube, Facebook "
                "and TikTok URLs are supported."
            )
        ), 400

    max_height = {
        "480": 480,
        "720": 720,
        "1080": 1080
    }.get(requested_quality, 480)

    job_id = uuid.uuid4().hex

    job_dir = DOWNLOAD_DIR / job_id

    job_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_template = str(
        job_dir / "%(title).80s.%(ext)s"
    )

    options = {

        "quiet": True,

        "no_warnings": True,

        "noplaylist": True,

        "format": (
            f"bestvideo[height<={max_height}]"
            f"+bestaudio/"
            f"best[height<={max_height}]/"
            f"best"
        ),

        "merge_output_format": "mp4",

        "outtmpl": output_template,

        "restrictfilenames": True,

        "windowsfilenames": True,

        "max_filesize": MAX_FILE_SIZE,

        "http_headers": {

            "User-Agent":
                "Mozilla/5.0 "
                "(Linux; Android 14) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/125.0.0.0 "
                "Mobile Safari/537.36",

            "Accept": "*/*",

            "Accept-Language":
                "en-US,en;q=0.9"
        }
    }

    # Add cookiefile if exists
    if COOKIE_FILE.exists():
        options["cookiefile"] = str(COOKIE_FILE)

    try:

        with yt_dlp.YoutubeDL(options) as ydl:

            info = ydl.extract_info(
                video_url,
                download=True
            )

            title = (
                info.get("title")
                or "Video"
            )

        files = [
            path
            for path in job_dir.iterdir()
            if path.is_file()
        ]

        if not files:

            raise RuntimeError(
                "Download completed but no file was created."
            )

        output_file = max(
            files,
            key=lambda path:
                path.stat().st_mtime
        )

        return jsonify(
            success=True,
            title=title,
            download_url=(
                f"/file/"
                f"{job_id}/"
                f"{output_file.name}"
            )
        )

    except Exception as exc:

        shutil.rmtree(
            job_dir,
            ignore_errors=True
        )

        return jsonify(
            success=False,
            error=clean_error(exc)
        ), 500


@app.route("/file/<job_id>/<filename>")
@limiter.limit("20 per minute")
def serve_file(job_id, filename):

    job_dir = (
        DOWNLOAD_DIR /
        job_id
    )

    if not job_dir.exists():
        return jsonify(
            success=False,
            error="File expired or not found."
        ), 404

    requested_file = (
        job_dir /
        filename
    ).resolve()

    try:

        requested_file.relative_to(
            job_dir.resolve()
        )

    except ValueError:

        return jsonify(
            success=False,
            error="Invalid file path."
        ), 400

    if not requested_file.is_file():

        return jsonify(
            success=False,
            error="File not found."
        ), 404

    return send_file(
        requested_file,
        as_attachment=True,
        download_name=requested_file.name
    )


# =========================================================
# LOCAL SERVER
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
            )
