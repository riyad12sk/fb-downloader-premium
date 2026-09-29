import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from flask import Flask, jsonify, render_template_string, request, send_file
import yt_dlp

app = Flask(__name__)

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Downloaded files are automatically removed after this amount of time.
MAX_FILE_AGE = 30 * 60

# Cleanup runs every 10 minutes.
CLEANUP_INTERVAL = 10 * 60

# Maximum download size: 500 MB
MAX_FILE_SIZE = 500 * 1024 * 1024

# --------------------------------------------------
# HTML FRONTEND
# --------------------------------------------------

HTML = r""" 
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BLACK CAT — Universal Video Downloader</title>
<style>
  body { font-family: Arial, sans-serif; background: #0f0f0f; color: #fff; text-align: center; padding: 20px; }
  .container { max-width: 500px; margin: auto; background: #1f1f1f; padding: 20px; border-radius: 10px; }
  input[type="url"] { width: 80%; padding: 10px; margin: 10px 0; border-radius: 5px; border: none; }
  button { padding: 10px 20px; background: #e50914; color: white; border: none; border-radius: 5px; cursor: pointer; }
  button:hover { background: #b20710; }
</style>
</head>
<body>
<div class="container">
  <h2>🐈‍⬛ BLACK CAT</h2>
  <h3>UNIVERSAL VIDEO DOWNLOADER</h3>
  <form id="downloadForm" onsubmit="event.preventDefault(); downloadVideo();">
    <p>Video URL</p>
    <input id="url" type="url" placeholder="Paste a public video link here..." autocomplete="off">
    <br>
    <div>
      <label><input type="radio" name="quality" value="480" checked> 480p</label>
      <label><input type="radio" name="quality" value="720"> 720p</label>
      <label><input type="radio" name="quality" value="1080"> 1080p</label>
    </div>
    <br>
    <button id="downloadBtn" type="button" onclick="downloadVideo()">DOWNLOAD VIDEO</button>
  </form>
  <div id="result" style="margin-top: 20px;"></div>
</div>
<script>
  async function downloadVideo() {
    const url = document.getElementById('url').value;
    const quality = document.querySelector('input[name="quality"]:checked').value;
    const btn = document.getElementById('downloadBtn');
    const result = document.getElementById('result');
    if (!url) { alert('Please enter a URL'); return; }
    btn.innerText = 'Downloading...';
    btn.disabled = true;
    try {
      const res = await fetch('/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, quality })
      });
      const data = await res.json();
      if (data.success) {
        result.innerHTML = `<p><b>Title:</b> ${data.title}</p><a href="${data.download_url}" style="color: #4682b4;" download>⬇ DOWNLOAD READY VIDEO</a>`;
      } else {
        result.innerHTML = `<p style="color: red;">Error: ${data.error}</p>`;
      }
    } catch (err) {
      result.innerHTML = `<p style="color: red;">An unexpected error occurred.</p>`;
    } finally {
      btn.innerText = 'DOWNLOAD VIDEO';
      btn.disabled = false;
    }
  }
</script>
</body>
</html>
"""

# --------------------------------------------------
# CLEANUP
# --------------------------------------------------


def cleanup_old_files():
  while True:
    try:
      now = time.time()
      for item in DOWNLOAD_DIR.iterdir():
        try:
          age = now - item.stat().st_mtime
          if age > MAX_FILE_AGE:
            if item.is_dir():
              shutil.rmtree(item, ignore_errors=True)
            else:
              item.unlink(missing_ok=True)
        except OSError:
          pass
    except Exception:
      pass
    time.sleep(CLEANUP_INTERVAL)


threading.Thread(target=cleanup_old_files, daemon=True).start()

# --------------------------------------------------
# HOME
# --------------------------------------------------


@app.route("/")
def home():
  return render_template_string(HTML)


# --------------------------------------------------
# DOWNLOAD
# --------------------------------------------------


@app.route("/download", methods=["POST"])
def download_video():
  data = request.get_json(silent=True) or {}
  video_url = str(data.get("url", "")).strip()
  requested_quality = str(data.get("quality", "480")).strip()

  # Basic URL validation
  if not video_url:
    return jsonify(success=False, error="Video URL is required."), 400

  if not video_url.lower().startswith(("http://", "https://")):
    return jsonify(
        success=False, error="Only HTTP/HTTPS URLs are allowed."
    ), 400

  # Allowed quality values
  quality_map = {"480": 480, "720": 720, "1080": 1080}

  max_height = quality_map.get(requested_quality, 480)

  # Unique job directory
  job_id = uuid.uuid4().hex
  job_dir = DOWNLOAD_DIR / job_id
  job_dir.mkdir(parents=True, exist_ok=True)

  # Safe output filename template
  output_template = str(job_dir / "%(title).80s.%(ext)s")

  options = {
      "quiet": True,
      "no_warnings": True,
      "noplaylist": True,
      "format": (
          f"best[ext=mp4][height<={max_height}]/best[height<={max_height}]/best"
      ),
      "outtmpl": output_template,
      "restrictfilenames": True,
      "windowsfilenames": True,
      "max_filesize": MAX_FILE_SIZE,
      "socket_timeout": 30,
      "retries": 2,
      "fragment_retries": 2,
      "continuedl": True,
      "overwrites": True,
  }

  try:
    with yt_dlp.YoutubeDL(options) as ydl:
      info = ydl.extract_info(video_url, download=True)

    title = info.get("title") or "Video"
    actual_height = info.get("height")

    # Find downloaded file
    files = [path for path in job_dir.iterdir() if path.is_file()]

    if not files:
      raise RuntimeError("Video file was not created.")

    output_file = max(files, key=lambda path: path.stat().st_mtime)

    # Final safety check
    try:
      output_file.resolve().relative_to(job_dir.resolve())
    except ValueError:
      raise RuntimeError("Invalid output file.")

    # Do not allow an unexpectedly large file
    if output_file.stat().st_size > MAX_FILE_SIZE:
      shutil.rmtree(job_dir, ignore_errors=True)
      return jsonify(
          success=False, error="The downloaded file is too large."
      ), 413

    encoded_filename = quote(output_file.name, safe="")
    download_url = "/file/" + job_id + "/" + encoded_filename

    return jsonify(
        success=True,
        title=title,
        height=actual_height,
        download_url=download_url,
    )

  except Exception as exc:
    shutil.rmtree(job_dir, ignore_errors=True)
    message = str(exc).strip()
    if not message:
      message = "The video could not be downloaded."
    return jsonify(success=False, error=message[-1200:]), 500


# --------------------------------------------------
# SERVE DOWNLOADED FILE
# --------------------------------------------------


@app.route("/file/<job_id>/<path:filename>")
def serve_file(job_id, filename):
  # Basic job ID validation
  if not job_id.isalnum():
    return jsonify(success=False, error="Invalid job ID."), 400

  job_dir = DOWNLOAD_DIR / job_id
  file_path = job_dir / filename

  # Prevent path traversal
  try:
    file_path.resolve().relative_to(job_dir.resolve())
  except ValueError:
    return jsonify(success=False, error="Invalid file path."), 400

  if not file_path.is_file():
    return jsonify(success=False, error="File not found or expired."), 404

  return send_file(
      file_path, as_attachment=True, download_name=file_path.name, conditional=True
  )


# --------------------------------------------------
# HEALTH CHECK & PING (UPTIMEROBOT)
# --------------------------------------------------


@app.route("/health")
def health():
  return jsonify(status="ok")


@app.route("/ping")
def ping():
  return "pong", 200


# --------------------------------------------------
# APPLICATION START
# --------------------------------------------------


if __name__ == "__main__":
  port = int(os.environ.get("PORT", "5000"))
  print("\n🐈‍⬛ BLACK CAT — Universal Video Downloader")
  print("🌐 Server running on port " + str(port) + "\n")
  app.run(host="0.0.0.0", port=port, debug=False)
