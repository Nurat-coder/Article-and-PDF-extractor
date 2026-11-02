import ipaddress
import socket
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

import httpx
import pymupdf
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from trafilatura import extract

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_HTML_BYTES = 3 * 1024 * 1024
MAX_PAGES = 200
MAX_REDIRECTS = 3
RATE_LIMIT, WINDOW = 20, 60  # 20 requests per minute per IP

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
hits = defaultdict(deque)

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; object-src 'none'; "
                               "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


@app.middleware("http")
async def security(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        ip = request.client.host if request.client else "unknown"
        now, q = time.monotonic(), hits[ip]
        while q and now - q[0] > WINDOW:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            return JSONResponse({"detail": "Too many requests. Wait a minute and try again."}, 429)
        q.append(now)
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class UrlIn(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


def check_url(url: str) -> None:
    """Block non-web links and anything pointing at private/internal networks (SSRF)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise HTTPException(400, "Enter a valid http or https link.")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise HTTPException(400, "Could not find that website.")
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise HTTPException(400, "That address is not allowed.")


def fetch_html(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (ArticleExtractor)"}
    with httpx.Client(follow_redirects=False, timeout=10, headers=headers) as client:
        for _ in range(MAX_REDIRECTS + 1):
            check_url(url)  # re-checked on every redirect hop
            try:
                with client.stream("GET", url) as r:
                    if r.is_redirect:
                        url = str(r.url.join(r.headers.get("location", "")))
                        continue
                    if r.status_code != 200:
                        raise HTTPException(400, "The website refused the request or is down.")
                    if "html" not in r.headers.get("content-type", ""):
                        raise HTTPException(400, "That link is not a web page.")
                    data = b""
                    for chunk in r.iter_bytes():
                        data += chunk
                        if len(data) > MAX_HTML_BYTES:
                            raise HTTPException(413, "That page is too large.")
                    return data.decode(r.encoding or "utf-8", errors="replace")
            except httpx.HTTPError:
                raise HTTPException(400, "Could not load that page. Check the link.")
    raise HTTPException(400, "Too many redirects.")


@app.post("/api/extract/url")
def extract_url(body: UrlIn):
    text = extract(fetch_html(body.url.strip()))
    if not text:
        raise HTTPException(422, "No article text found on that page.")
    return {"text": text}


@app.post("/api/extract/pdf")
def extract_pdf(file: UploadFile = File(...)):
    data = file.file.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, "PDF is too large (max 10 MB).")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "That file is not a PDF.")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise HTTPException(400, "Could not open that PDF.")
    with doc:
        if doc.needs_pass:
            raise HTTPException(400, "This PDF is password protected.")
        if doc.page_count > MAX_PAGES:
            raise HTTPException(400, f"PDF has too many pages (max {MAX_PAGES}).")
        text = "\n\f\n".join(page.get_text() for page in doc)
    if not text.strip():
        raise HTTPException(422, "No text found. This may be a scanned PDF.")
    return {"text": text}


app.mount("/", StaticFiles(directory="static", html=True), name="static")