"""
Robo-Tester v3.x – FastAPI Control Plane (Single File)

Run with:
    uvicorn app:app --reload
"""

import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Literal
from threading import Thread
from uuid import uuid4
import re
import os
import uuid
import signal
from playwright.async_api import async_playwright
import sys
from dotenv import load_dotenv
from fastapi import WebSocket, WebSocketDisconnect
import base64
import asyncio
from fastapi.middleware.cors import CORSMiddleware
import sys
import json
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
from engines.orchestrator import Orchestrator
from fastapi.responses import FileResponse
from pathlib import Path
import os
from openai import AsyncOpenAI
import signal
import pandas as pd
from fastapi import BackgroundTasks
from fastapi.responses import FileResponse
from pathlib import Path
from checking import CheckingPipeline
from hello import SemanticTester
from datetime import datetime


######Phase 0
DEFAULT_TARGET_URL = os.getenv("TARGET_URL")
OPENAI_API_KEY         = os.getenv("OPENAI_API_KEY" )
SCREENSHOT_BASE    = Path("screenshots")

SUCCESS_URL_PATTERNS = ["dashboard","home","app","feed","inbox","profile","main","welcome","mosque","masjid","overview","portal"]
LOGIN_URL_PATTERNS   = ["sign-in","signin","login","log-in","auth","otp","verify"]

class LoginCredentials(BaseModel):
    email: str
    password: Optional[str] = None
    otp: Optional[str] = None
    target_url: Optional[str] = None

# ── JS injector ───────────────────────────────────────────────────────────────
INJECT_JS = """
() => {
    document.querySelectorAll('[data-agent-label]').forEach(el => el.remove());
    const pageTitle = document.title || '';
    const textNodes = Array.from(document.querySelectorAll('h1,h2,h3,h4,label,p,span.title,div.title'))
                          .map(el => el.innerText.trim())
                          .filter(t => t.length > 1 && t.length < 200)
                          .slice(0, 20).join(' | ');
    const pageContext = (pageTitle + ' | ' + textNodes).substring(0, 800);
    const SELECTORS = ['input:not([type="hidden"])','button','a[href]','[role="button"]',
        '[role="link"]','[role="textbox"]','select','textarea','[onclick]','[tabindex]:not([tabindex="-1"])'];
    function collectElements(root) {
        let found = [];
        const walker = root.querySelectorAll ? root : root.shadowRoot;
        if (!walker) return found;
        SELECTORS.forEach(sel => { try { walker.querySelectorAll(sel).forEach(el => { if (!found.includes(el)) found.push(el); }); } catch(e) {} });
        walker.querySelectorAll('*').forEach(el => { if (el.shadowRoot) found = found.concat(collectElements(el.shadowRoot)); });
        return found;
    }
    const elements = collectElements(document);
    let counter = 1;
    const map = { __pageContext__: pageContext };
    elements.forEach(el => {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        if (rect.top < 0 || rect.top > window.innerHeight + 200) return;
        const id = counter++;
        let labelText = '';
        if (el.id) { const lbl = document.querySelector('label[for="' + el.id + '"]'); if (lbl) labelText = lbl.innerText.trim(); }
        if (!labelText && el.closest('label')) labelText = el.closest('label').innerText.trim();
        if (!labelText) { const prev = el.previousElementSibling; if (prev && ['LABEL','SPAN','DIV','P'].includes(prev.tagName)) labelText = prev.innerText.trim().substring(0, 80); }
        map[id] = { tag: el.tagName.toLowerCase(), type: el.type || '', placeholder: el.placeholder || '',
            name: el.name || '', elemId: el.id || '', text: (el.innerText || el.value || '').substring(0, 80).trim(),
            ariaLabel: el.getAttribute('aria-label') || '', labelText: labelText,
            rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height } };
        const box = document.createElement('div');
        box.setAttribute('data-agent-label', id);
        box.style.cssText = 'position:fixed;top:'+rect.top+'px;left:'+rect.left+'px;width:'+rect.width+'px;height:'+rect.height+'px;border:2px solid red;pointer-events:none;z-index:999999;box-sizing:border-box;';
        const badge = document.createElement('div');
        badge.textContent = id;
        badge.style.cssText = 'position:absolute;top:-18px;left:0;background:red;color:white;font-size:11px;font-weight:bold;padding:1px 4px;border-radius:3px;font-family:monospace;white-space:nowrap;';
        box.appendChild(badge);
        document.body.appendChild(box);
    });
    return map;
}
"""

SYSTEM_PROMPT = """You are a web login automation agent. You receive:
1. A screenshot of a web page with red-boxed numbered elements
2. The current URL
3. ALL visible page text (title, headings, labels, paragraphs) as "Page context"
4. An element map with HTML attributes for each numbered box

YOUR PROCESS - always do this in order:
STEP A) Read the page context and URL first. Identify the CURRENT PAGE TYPE:
  - "email_input_page"   -> page is asking for email / phone / username to begin login
  - "otp_page"           -> page is asking for a verification code / OTP / kode verifikasi
  - "password_page"      -> page is asking for a password
  - "dashboard_page"     -> user is successfully logged in
  - "other_page"         -> anything else

STEP B) Based on page type, decide the single next action.

OUTPUT - return EXACTLY this JSON and nothing else (no markdown, no explanation):
{"page_type": "<type>", "action": "<CLICK #id | TYPE #id | STUCK>", "reason": "<one sentence>"}

Rules:
- CLICK for buttons and links
- TYPE for input fields - always pick the first EMPTY/unfilled input
- On otp_page: the text input IS the OTP field regardless of its HTML attributes
- On email_input_page: TYPE the email input, then CLICK the submit button
- NEVER return DONE - the system handles login detection automatically via URL
- STUCK only if you truly cannot determine the next action
- If a field already has text in it, skip it and look for the next empty field or button to click

LANGUAGE NOTE - this site may use Indonesian (Bahasa Indonesia):
"Masukkan kode verifikasi" = "Enter verification code" -> otp_page
"Kirim kode verifikasi ke Email" = "Send code to Email" -> button to click
"Verifikasi & Lanjutkan" = "Verify & Continue" -> OTP submit button
"Email atau Nomor Ponsel" = "Email or Phone Number" -> email_input_page
"Tersisa 01:51" = "Time remaining 01:51" = OTP countdown timer (confirms otp_page)
"""

# ── Helpers ───────────────────────────────────────────────────────────────────
def is_success_url(url): return any(p in url.lower() for p in SUCCESS_URL_PATTERNS)
def is_login_url(url):   return any(p in url.lower() for p in LOGIN_URL_PATTERNS)


# ── Session ───────────────────────────────────────────────────────────────────
class LoginSession:
    def __init__(self, session_id: str, ws: WebSocket, creds: LoginCredentials):
        self.session_id     = session_id
        self.ws             = ws
        self.email          = creds.email
        self.password       = creds.password or ""
        self.otp            = creds.otp or ""
        self.target_url     = (creds.target_url or DEFAULT_TARGET_URL).strip()
        self.otp_event      = asyncio.Event()
        self.screenshot_dir = SCREENSHOT_BASE / session_id / "phase0_gpt"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.client         = AsyncOpenAI(api_key=OPENAI_API_KEY)

    async def send(self, payload: dict):
        await self.ws.send_text(json.dumps(payload))

    async def log(self, msg: str, color: str = "cyan"):
        await self.send({"type": "log", "message": msg, "color": color})

    async def send_screenshot(self, step: int, png_bytes: bytes):
        filename = f"step_{step:02d}.png"
        path = self.screenshot_dir / filename
        path.write_bytes(png_bytes)
        b64 = base64.b64encode(png_bytes).decode()
        await self.send({
            "type": "screenshot", "session_id": self.session_id,
            "phase": "phase0_gpt", "filename": filename,
            "path": str(path), "data": b64,
        })
        return filename

    def get_credential_for(self, page_type: str, page_context: str, elem_info: dict) -> Optional[str]:
        if page_type == "email_input_page":
            return self.email
        if page_type == "password_page":
            return self.password or None
        if page_type == "otp_page":
            return None

        combined = " ".join([
            elem_info.get("type", ""), elem_info.get("placeholder", ""),
            elem_info.get("name", ""), elem_info.get("ariaLabel", ""),
            elem_info.get("labelText", ""), page_context,
        ]).lower()

        if any(k in combined for k in ["email","mail","ponsel","phone","username"]):
            return self.email
        if any(k in combined for k in ["password","passwd","sandi"]):
            return self.password or None
        if any(k in combined for k in ["otp","code","verif","pin","token","kode"]):
            return None
        return None

    async def get_otp(self) -> str:
        if self.otp:
            val = self.otp
            self.otp = ""
            return val
        await self.send({
            "type": "input_needed", "field": "otp",
            "session_id": self.session_id,
            "message": 'OTP needed - send: {"otp": "123456"}',
        })
        self.otp_event.clear()
        await asyncio.wait_for(self.otp_event.wait(), timeout=120)
        val = self.otp
        self.otp = ""
        return val

    def supply_otp(self, value: str):
        self.otp = value
        self.otp_event.set()

    async def ask_gpt(self, screenshot_b64: str, element_map: dict,
                      page_context: str, current_url: str, step: int) -> dict:
        elem_summary = json.dumps({
            k: {f: v.get(f, "") for f in ["tag","type","placeholder","labelText","text","ariaLabel","name"]}
            for k, v in element_map.items()
        }, indent=2)

        user_text = (
            f"Step {step}\nCurrent URL  : {current_url}\n"
            f"Page context : {page_context}\n\nElement map  :\n{elem_summary}\n\n"
            "Read the page context above first to determine page type, then return your JSON."
        )

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}", "detail": "high"}},
                ]},
            ],
            max_tokens=150,
            temperature=0,
        )

        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        try:
            return json.loads(raw)
        except Exception:
            m = re.search(r"(CLICK\s*#\d+|TYPE\s*#\d+|DONE|STUCK)", raw, re.IGNORECASE)
            return {"page_type": "unknown", "action": m.group(1) if m else "STUCK", "reason": raw[:120]}

    async def run(self):
        await self.log(f"Session {self.session_id} started -> {self.target_url}", "green")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, slow_mo=150)
            ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
            page = await ctx.new_page()

            await self.log(f"Opening {self.target_url}...")
            await page.goto(self.target_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(1.5)

            step = 0
            last_actions: list[str] = []

            while True:
                step += 1
                current_url = page.url
                await self.log(f"[Step {step}] {current_url}")

                if is_success_url(current_url) and not is_login_url(current_url):
                    await self.log("Login detected by URL!", "green")
                    break

                try:
                    raw_map = await page.evaluate(INJECT_JS)
                except Exception as e:
                    await self.log(f"JS injection failed: {e} - retrying", "yellow")
                    await asyncio.sleep(2)
                    raw_map = await page.evaluate(INJECT_JS)

                page_context = raw_map.pop("__pageContext__", "")
                element_map = raw_map

                if not element_map:
                    await self.log("No elements found - waiting 2s...", "yellow")
                    await asyncio.sleep(2)
                    continue

                await self.log(f"Found {len(element_map)} elements | {page_context[:100]}...")

                png_bytes = await page.screenshot(full_page=False)
                filename = await self.send_screenshot(step, png_bytes)
                await self.log(f"Screenshot: {filename}")

                screenshot_b64 = base64.b64encode(png_bytes).decode()

                await self.log("Calling GPT-4o-mini...")
                try:
                    result = await self.ask_gpt(screenshot_b64, element_map, page_context, current_url, step)
                except Exception as e:
                    await self.log(f"GPT error: {e}", "red")
                    await asyncio.sleep(3)
                    continue

                page_type = result.get("page_type", "unknown")
                decision = result.get("action", "STUCK").strip()
                reason = result.get("reason", "")
                await self.log(f"GPT -> [{page_type}] {decision} | {reason}")

                if page_type == "dashboard_page":
                    if is_success_url(current_url) and not is_login_url(current_url):
                        await self.log("Confirmed dashboard.", "green")
                        break
                    await self.log("GPT says dashboard but URL looks like login - continuing.", "yellow")

                if re.match(r"DONE", decision, re.IGNORECASE):
                    await self.log("GPT returned DONE - ignoring.", "yellow")
                    await asyncio.sleep(2)
                    continue

                if re.match(r"STUCK", decision, re.IGNORECASE):
                    await self.log("GPT stuck - waiting 3s...", "yellow")
                    await asyncio.sleep(3)
                    continue

                click_m = re.match(r"CLICK\s*#(\d+)", decision, re.IGNORECASE)
                type_m  = re.match(r"TYPE\s*#(\d+)",  decision, re.IGNORECASE)

                if click_m:
                    elem_id = int(click_m.group(1))
                    info = element_map.get(str(elem_id))
                    if not info:
                        await self.log(f"Element #{elem_id} not in map.", "yellow")
                        continue

                    action_sig = f"CLICK#{elem_id}"
                    last_actions.append(action_sig)
                    if last_actions.count(action_sig) > 3:
                        await self.log("Same button clicked 3+ times - resetting.", "yellow")
                        last_actions = []
                        await asyncio.sleep(2)
                        continue

                    btn_label = info.get("text") or info.get("ariaLabel") or "button"
                    await self.log(f"Clicking #{elem_id} - \"{btn_label[:60]}\"")
                    try:
                        r = info["rect"]
                        await page.mouse.click(r["left"] + r["width"]/2, r["top"] + r["height"]/2)
                        await asyncio.sleep(1.5)
                    except Exception as e:
                        await self.log(f"Click failed ({e}) - trying fallback", "yellow")
                        try:
                            await page.locator(f'[id="{info.get("elemId")}"]').first.click(timeout=3000)
                        except:
                            pass

                elif type_m:
                    elem_id = int(type_m.group(1))
                    info = element_map.get(str(elem_id))
                    if not info:
                        await self.log(f"Element #{elem_id} not in map.", "yellow")
                        continue

                    if page_type == "otp_page":
                        value = await self.get_otp()
                    else:
                        value = self.get_credential_for(page_type, page_context, info)
                        if value is None:
                            field_hint = info.get("placeholder") or info.get("labelText") or info.get("name") or "unknown"
                            await self.log(f"No credential for field #{elem_id} ({field_hint}) - skipping.", "yellow")
                            continue

                    if not value:
                        await self.log("Empty credential - skipping field.", "yellow")
                        continue

                    await self.log(f"Typing into #{elem_id} (page_type={page_type})...")
                    try:
                        r = info["rect"]
                        await page.mouse.click(r["left"] + r["width"]/2, r["top"] + r["height"]/2)
                        await asyncio.sleep(0.3)
                        await page.keyboard.type(value, delay=80)
                        await asyncio.sleep(0.8)
                    except Exception as e:
                        await self.log(f"Keyboard type failed ({e}) - trying fill", "yellow")
                        for selector in [
                            f'input[name="{info.get("name")}"]',
                            f'input[placeholder="{info.get("placeholder")}"]',
                            f'#{info.get("elemId")}',
                        ]:
                            try:
                                await page.locator(selector).first.fill(value, timeout=2000)
                                break
                            except:
                                continue
                else:
                    await self.log(f"Unrecognised action: \"{decision}\" - skipping.", "yellow")
                    await asyncio.sleep(1)
                    continue

                await asyncio.sleep(1.5)
                new_url = page.url
                if new_url != current_url:
                    await self.log(f"URL changed -> {new_url}")
                    if is_success_url(new_url) and not is_login_url(new_url):
                        await self.log("Login confirmed by URL change!", "green")
                        break

            auth_file = f"auth.json"
            state = await ctx.storage_state()
            local_storage = {}
            for origin in state.get("origins", []):
                for item in origin.get("localStorage", []):
                    local_storage[item["name"]] = item["value"]
            legacy = {
                "local_storage": local_storage,
                "session_storage": {},
                "cookies": state.get("cookies", []),
                "post_login_url": page.url
            }        
            with open(auth_file, "w") as f:
                json.dump(legacy, f, indent=2)
            await self.log(f"Session saved -> {auth_file}", "green")
            await browser.close()

        await self.send({"type": "done", "session_id": self.session_id, "auth_file": auth_file})

load_dotenv()

BASE_API_URL = os.getenv("BASE_API_URL", "http://127.0.0.1:8000")

# =====================================================================
# Pydantic Schemas
# =====================================================================
class SemanticStartRequest(BaseModel): #Hello.py
    url: str

class CheckingStartRequest(BaseModel):
    base_url: str

class CheckingResponse(BaseModel):
    status: str
    message: str

class StartTestRequest(BaseModel):
    mode: Literal["whitebox", "blackbox"]
    url: str
    goal: str
    steps: Optional[List[str]] = []

class StartTestResponse(BaseModel):
    test_id: str
    status: str

class TestStatusResponse(BaseModel):
    test_id: str
    status: str
    current_step: int
    max_steps: int
    last_action: Optional[str]
    assertions: List[str] = [] 
    summary: Optional[str] = None

class UserInputRequest(BaseModel):
    element_id: str
    value: str

class DiscoverRequest(BaseModel):
    target_url: str
    login_url: Optional[str] = None
    requires_auth: bool = True

# =====================================================================
# In-Memory Test Registry (can later move to Redis / DB)
# =====================================================================

TESTS: Dict[str, dict] = {}

def create_test(orchestrator: Orchestrator) -> str:
    test_id = str(uuid4())
    TESTS[test_id] = {
        "orchestrator": orchestrator,
        "status": "running",
        "report": None
    }
    return test_id

CHECKING_JOBS: Dict[str, dict] = {}

def create_checking_job(pipeline) -> str:
    job_id = str(uuid4())
    CHECKING_JOBS[job_id] = {
        "pipeline": pipeline,
        "status": "running"
    }
    return job_id

SEMANTIC_TESTS: Dict[str, dict] = {}

# =====================================================================
# FastAPI App
# =====================================================================

app = FastAPI(
    title="Robo-Tester API",
    version="3.1",
    description="API wrapper for Robo-Tester Autonomous Web Testing Agent"
)
active_sessions: dict[str, LoginSession] = {}



app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    print("⚠️  WARNING: OPENAI_API_KEY is not set")

# =====================================================================
# Health Check
# =====================================================================

@app.get("/health")
def health():
    return {"status": "ok"}
@app.websocket("/ws/login")
async def ws_login(websocket: WebSocket):
    await websocket.accept()

    session_id = str(uuid.uuid4())[:8]
    await websocket.send_text(json.dumps({
        "type": "connected",
        "session_id": session_id,
        "message": 'Send: {"email":"...","password":"(optional)","otp":"(optional)","target_url":"(optional)"}',
    }))

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=60)
        data = json.loads(raw)
        creds = LoginCredentials(**data)  # only email is required

        session = LoginSession(session_id, websocket, creds)
        active_sessions[session_id] = session

        agent_task = asyncio.create_task(session.run())

        async def listen_for_updates():
            while not agent_task.done():
                try:
                    msg = await asyncio.wait_for(websocket.receive_text(), timeout=1)
                    body = json.loads(msg)
                    if "otp" in body:
                        session.supply_otp(body["otp"])
                        await session.log(f"OTP received: {body['otp']}", "green")
                except asyncio.TimeoutError:
                    continue
                except WebSocketDisconnect:
                    agent_task.cancel()
                    break
                except Exception:
                    break

        listener_task = asyncio.create_task(listen_for_updates())

        try:
            await agent_task
        except asyncio.CancelledError:
            await websocket.send_text(json.dumps({"type": "error", "message": "Session cancelled"}))
        except Exception as e:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        finally:
            listener_task.cancel()
            active_sessions.pop(session_id, None)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        except:
            pass
    finally:
        active_sessions.pop(session_id, None)
# =====================================================================
# Start Test (Whitebox / Blackbox)
# =====================================================================

@app.post("/tests/start", response_model=StartTestResponse)
def start_test(payload: StartTestRequest):
    orchestrator = Orchestrator(
        api_key=OPENAI_API_KEY,
        headless=True
    )

    test_id = create_test(orchestrator)

    def run_test():
        try:
            goal = (
                payload.goal
                if payload.mode == "whitebox"
                else "\n".join(payload.steps) if payload.steps else payload.goal
            )

            result = orchestrator.run(
                url=payload.url,
                goal=goal
            )

            TESTS[test_id]["status"] = "completed"
            TESTS[test_id]["report"] = result

        except Exception as e:
            TESTS[test_id]["status"] = "failed"
            TESTS[test_id]["report"] = {"error": str(e)}

    Thread(target=run_test, daemon=True).start()

    return StartTestResponse(
        test_id=test_id,
        status="running"
    )

# =====================================================================
# Get Test Status (Live Progress)
# =====================================================================

# app.py

@app.get("/tests/{test_id}/status", response_model=TestStatusResponse)
def get_test_status(test_id: str):
    if test_id not in TESTS:
        raise HTTPException(status_code=404, detail="Test not found")

    orch: Orchestrator = TESTS[test_id]["orchestrator"]
    status = TESTS[test_id]["status"]

    return TestStatusResponse(
        test_id=test_id,
        status=status,
        current_step=orch.step_count,
        max_steps=orch.max_steps,
        last_action=orch.action_history[-1] if orch.action_history else None,
        assertions=orch.assertions,
        summary=orch.summary if status == "completed" else None
    )

# =====================================================================
# Get Final Test Report
# =====================================================================

@app.get("/tests/{test_id}/report")
def get_test_report(test_id: str):
    if test_id not in TESTS:
        raise HTTPException(status_code=404, detail="Test not found")

    if TESTS[test_id]["status"] != "completed":
        return {
            "status": TESTS[test_id]["status"],
            "message": "Test not completed yet"
        }

    return TESTS[test_id]["report"]

# =====================================================================
# Provide User Input (OTP / Form Fields)
# =====================================================================

@app.post("/tests/{test_id}/input")
def provide_user_input(test_id: str, payload: UserInputRequest):
    orch: Orchestrator = TESTS[test_id]["orchestrator"]

    orch.collected_credentials[payload.element_id] = payload.value

    orch.waiting_for_input = False
    orch.waiting_input_payload = None

    return {"status": "resumed"}

@app.get("/tests/{test_id}/waiting")
def check_waiting_state(test_id: str):
    if test_id not in TESTS:
        raise HTTPException(status_code=404)

    orch = TESTS[test_id]["orchestrator"]

    if orch.waiting_for_input:
        return {
            "waiting": True,
            "payload": orch.waiting_input_payload
        }

    return {"waiting": False}


# =====================================================================
# List All Tests
# =====================================================================

@app.get("/tests")
def list_tests():
    return {
        test_id: {
            "status": data["status"]
        }
        for test_id, data in TESTS.items()
    }


# =====================================================================
# Websocket Streaming (Screenshots)
# =====================================================================

@app.websocket("/ws/tests/{test_id}")
async def stream_browser(websocket: WebSocket, test_id: str):
    await websocket.accept()

    if test_id not in TESTS:
        await websocket.send_json({"error": "Invalid test_id"})
        await websocket.close()
        return

    orch = TESTS[test_id]["orchestrator"]

    try:
        while True:
            # Send latest screenshot if available
            screenshot_path = getattr(orch, "latest_screenshot", None)

            if orch.step_count > 0 and screenshot_path and os.path.exists(screenshot_path):
                with open(screenshot_path, "rb") as f:
                    img_bytes = f.read()

                await websocket.send_json({
                    "type": "frame",
                    "image": base64.b64encode(img_bytes).decode("utf-8"),
                    "step": orch.step_count
                })

            await asyncio.sleep(0.3)  # ~3 FPS (safe)
    except WebSocketDisconnect:
        print("🔌 WebSocket disconnected")

#==========================================================================
# CHECKING.PY ENDPOINTS
#==========================================================================
@app.post("/checking/start")
async def start_checking(payload: CheckingStartRequest):

    pipeline = CheckingPipeline(base_url=payload.base_url)
    job_id = create_checking_job(pipeline)

    async def wrapped():
        try:
            await pipeline.run()
            CHECKING_JOBS[job_id]["status"] = pipeline.status
        except Exception as e:
            pipeline.status = "failed"
            pipeline.error = str(e)
            CHECKING_JOBS[job_id]["status"] = "failed"

    asyncio.create_task(wrapped())

    return {
        "job_id": job_id,
        "status": "running"
    }


@app.get("/checking/{job_id}/status")
def checking_status(job_id: str):
    if job_id not in CHECKING_JOBS:
        raise HTTPException(status_code=404)

    pipeline = CHECKING_JOBS[job_id]["pipeline"]

    return {
        "status": pipeline.status,
        "current_url": pipeline.current_url,
        "total_urls": pipeline.total_urls,
        "completed_urls": pipeline.completed_urls,
        "completed_reports": pipeline.completed_reports,
        "message": pipeline.ws_messages[-1]["message"] if pipeline.ws_messages else "Initializing...",
        "error": pipeline.error
    }

@app.websocket("/ws/checking/{job_id}")
async def stream_checking_browser(websocket: WebSocket, job_id: str):
    await websocket.accept()

    if job_id not in CHECKING_JOBS:
        await websocket.send_json({
            "type": "error",
            "message": "Invalid job_id"
        })
        await websocket.close()
        return

    pipeline = CHECKING_JOBS[job_id]["pipeline"]

    # ✅ If pipeline already finished before WS connected
    if pipeline.status == "completed":
        # Send all historical report messages first
        for msg in getattr(pipeline, "ws_messages", []):
            await websocket.send_json(msg)
            
        await websocket.send_json({
            "type": "done",
            "message": "Discovering Links completed !! , Started Exploration By Interacting Elements",
            "completed": pipeline.completed_urls,
            "total": pipeline.total_urls
        })
        
        await websocket.close()
        return

    if pipeline.status == "failed":
        await websocket.send_json({
            "type": "error",
            "message": pipeline.error or "Exploration failed"
        })
        await websocket.close()
        return

    last_msg_idx = 0  # 👈 NEW: Track which messages we've already sent

    try:
        while True:
            # 👇 NEW: Send any new URL completion reports
            while hasattr(pipeline, "ws_messages") and last_msg_idx < len(pipeline.ws_messages):
                msg = pipeline.ws_messages[last_msg_idx]
                await websocket.send_json(msg)
                last_msg_idx += 1

            # 🔹 1️⃣ Check lifecycle FIRST, but ONLY close if all messages are sent
            if pipeline.status == "completed" and last_msg_idx == len(getattr(pipeline, "ws_messages", [])):
                await websocket.send_json({
                    "type": "done",
                    "message": "Exploration completed !!",
                    "completed": pipeline.completed_urls,
                    "total": pipeline.total_urls
                })
                await websocket.close()
                break

            if pipeline.status == "failed":
                await websocket.send_json({
                    "type": "error",
                    "message": pipeline.error or "Exploration failed"
                })
                await websocket.close()
                break

            # 🔹 2️⃣ Send screenshot frame if available
            screenshot_path = getattr(pipeline, "latest_screenshot", None)

            if screenshot_path and os.path.exists(screenshot_path):
                with open(screenshot_path, "rb") as f:
                    img_bytes = f.read()

                await websocket.send_json({
                    "type": "frame",
                    "image": base64.b64encode(img_bytes).decode("utf-8"),
                    "current_url": pipeline.current_url,
                    "completed": pipeline.completed_urls,
                    "total": pipeline.total_urls
                })

            await asyncio.sleep(0.3)

    except WebSocketDisconnect:
        print("🔌 Checking WebSocket disconnected")

@app.post("/terminate-and-restart")
def terminate_and_restart():
    # Perform any cleanup/save reports here...
    print("Termination requested. Restarting Master service...")
    
    # This sends a SIGTERM to the parent (the Gunicorn Master)
    # Systemd will see the Master die and restart it immediately.
    os.kill(os.getppid(), signal.SIGTERM)
    
    return {"status": "Restarting system..."}


@app.post("/terminate")
def terminate_program(background_tasks: BackgroundTasks):
    """
    Terminates the FastAPI server process immediately.
    """
    def kill_process():
        # Get the current process ID (PID)
        pid = os.getpid()
        print(f"🛑 Termination signal received. Killing PID: {pid}")
        # Send SIGTERM signal to self to trigger a clean shutdown or SIGKILL for immediate stop
        os.kill(pid, signal.SIGTERM)

    # Use a background task to ensure the API returns a response before shutting down
    background_tasks.add_task(kill_process)
    
    return {
        "status": "terminating",
        "message": "The server is shutting down. Check console logs for PID status."
    }

# =====================================================================
# Semantic Driver (hello.py) Endpoints
# =====================================================================

@app.post("/semantic/start")
async def start_semantic_test(payload: SemanticStartRequest, background_tasks: BackgroundTasks):
    """
    Triggers the autonomous testing logic from hello.py (SemanticTester).
    """
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")

    test_id = str(uuid4())
    
    # Initialize the tester
    # Note: Ensure auth.json exists in your root directory as hello.py expects it
    tester = SemanticTester(openai_api_key=OPENAI_API_KEY)
    
    SEMANTIC_TESTS[test_id] = {
        "status": "running",
        "url": payload.url,
        "tester": tester,
        "start_time": datetime.now().isoformat()
    }

    async def run_semantic_logic():
        try:
            # We call the run method from hello.py
            await tester.run(payload.url)
            SEMANTIC_TESTS[test_id]["status"] = "completed"
        except Exception as e:
            print(f"❌ Semantic Test Failed: {str(e)}")
            SEMANTIC_TESTS[test_id]["status"] = "failed"
            SEMANTIC_TESTS[test_id]["error"] = str(e)

    # Run the playwright loop in the background
    background_tasks.add_task(run_semantic_logic)

    return {
        "test_id": test_id,
        "status": "running",
        "message": "Semantic Driver started"
    }

@app.get("/semantic/{test_id}/status")
def get_semantic_status(test_id: str):
    """
    Check progress of the Semantic Driver.
    """
    if test_id not in SEMANTIC_TESTS:
        raise HTTPException(status_code=404, detail="Semantic test not found")

    data = SEMANTIC_TESTS[test_id]
    tester: SemanticTester = data["tester"]
    

    return {
        "test_id": test_id,
        "status": data["status"],
        "current_step": tester.step,
        "history_count": len(tester.history),
        "last_action": tester.history[-1]["decision"] if tester.history else None,
        "error": data.get("error")
    }

@app.get("/semantic/{test_id}/download-report")
async def download_semantic_report(test_id: str):
    """
    Locates the Excel file generated by hello.py and sends it to the frontend.
    """
    if test_id not in SEMANTIC_TESTS:
        raise HTTPException(status_code=404, detail="Test record not found")

    tester = SEMANTIC_TESTS[test_id]["tester"]
    session_id = tester.session_id
    
    # Path where hello.py saves the files
    output_dir = "semantic_test_output"
    # Ensure your ReportGenerator in hello.py is named this way
    report_filename = f"test_report_{session_id}.xlsx" 
    report_path = os.path.join(output_dir, report_filename)

    if not os.path.exists(report_path):
        raise HTTPException(status_code=404, detail="Excel report not found.")

    return FileResponse(
        path=report_path, 
        filename=report_filename, 
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

# =====================================================================
# Semantic Driver WebSocket (Live Screenshots)
# =====================================================================

@app.websocket("/ws/semantic/{test_id}")
async def stream_semantic_browser(websocket: WebSocket, test_id: str):
    await websocket.accept()

    # Verify the test exists in memory
    if test_id not in SEMANTIC_TESTS:
        await websocket.send_json({"error": "Invalid semantic test_id or session expired"})
        await websocket.close()
        return

    data = SEMANTIC_TESTS[test_id]
    tester: SemanticTester = data["tester"]
    last_sent_step = -1
    last_log_idx = 0 

    try:
        while True:
            # Check if the tester has a new screenshot and if it actually exists on disk
            screenshot_path = getattr(tester, "latest_screenshot", None)
            current_step = tester.step

            if screenshot_path and os.path.exists(screenshot_path):
                # Optional: Only send if it's a new step to save bandwidth
                if current_step > last_sent_step:
                    with open(screenshot_path, "rb") as f:
                        img_bytes = f.read()

                    await websocket.send_json({
                        "type": "frame",
                        "image": base64.b64encode(img_bytes).decode("utf-8"),
                        "step": current_step,
                        "url": getattr(tester, "current_url", "N/A"),
                        "status": data["status"]
                    })
                    last_sent_step = current_step

            # If the test finishes, send a final 'done' message and close
            if data["status"] in ["completed", "failed"]:
                # 1. Define the report path
                report_filename = f"test_report_{tester.session_id}.xlsx"
                report_path = os.path.join("semantic_test_output", report_filename)
                
                # 2. Prepare file data (initialize as None)
                excel_b64 = None
                
                # 3. Read and encode if it exists
                if os.path.exists(report_path):
                    with open(report_path, "rb") as f:
                        excel_b64 = base64.b64encode(f.read()).decode("utf-8")
                
                # 4. Send the enriched message
                await websocket.send_json({
                    "type": "done",
                    "status": data["status"],
                    "message": "Phase 2 Exploration Finished",
                    "excel_base64": excel_b64,   
                    "download_url": f"{BASE_API_URL}/semantic/{tester.session_id}/download-report",    # The file content
                    "excel_filename": report_filename # Filename for the frontend
                })
                break

            
            while last_log_idx < len(tester.ws_logs):
                await websocket.send_json({
                    "type": "log",
                    **tester.ws_logs[last_log_idx]
                })
                last_log_idx += 1
            await asyncio.sleep(0.5) # ~2 FPS update rate
            
    except WebSocketDisconnect:
        print(f"🔌 Semantic WebSocket disconnected for {test_id}")
    except Exception as e:
        print(f"⚠️ WebSocket Error: {str(e)}")
    finally:
        try:
            await websocket.close()
        except:
            pass


# Bridge for test/start to start the phase 3 which reads the excel sheet and return url, test stories

@app.post("/semantic/{test_id}/convert-to-orchestrator")
async def convert_stories_to_tests(test_id: str, background_tasks: BackgroundTasks):
    """
    Dynamically extracts the URL and stories from the Phase 2 session 
    to feed into the Orchestrator.
    """
    output_dir = "semantic_test_output"
    
    # 1. Resolve Session Data and URL dynamically
    if test_id in SEMANTIC_TESTS:
        session_id = SEMANTIC_TESTS[test_id]["tester"].session_id
        # Use the URL that was actually used in the Phase 2 session
        starting_url = SEMANTIC_TESTS[test_id]["url"] 
    else:
        # Fallback if server restarted: check if test_id is a timestamp
        session_id = test_id
        # If the session is no longer in memory, we could theoretically parse 
        # the URL from the Excel 'Summary' sheet if needed.
        raise HTTPException(
            status_code=404, 
            detail="Session not found in memory. URL cannot be determined dynamically."
        )
    
    report_path = os.path.join(output_dir, f"test_report_{session_id}.xlsx")

    if not os.path.exists(report_path):
        raise HTTPException(status_code=404, detail="Excel report not found on disk.")

    try:
        # 2. Read the 'Execution Plan' sheet
        df = pd.read_excel(report_path, sheet_name='Execution Plan', skiprows=13)
        tasks_to_run = []

        for _, row in df.iterrows():
            steps_text = str(row['Test Steps'])
            feature_name = str(row['Feature / Context'])
            
            if "EXPLORE" not in steps_text:
                continue

            # 3. Extract all steps as a single goal
            # raw_steps = re.findall(r"'(.*?)'", steps_text) 
            raw_steps = []
            for line in steps_text.split('\n'):
                line = line.strip()
                if 'EXPLORE' in line:
                    cleaned = re.sub(r"^\d+\.\s*EXPLORE\s*'?", "", line).rstrip("'").strip()
                    if cleaned:
                        raw_steps.append(cleaned)
            if not raw_steps:
                continue

            # Creating one single instruction encompassing all 8 steps
            combined_goal = f"Perform the '{feature_name}' workflow: " + " then ".join(raw_steps)

            tasks_to_run.append({
                "url": starting_url, # Dynamic URL from Phase 2 session
                "goal": combined_goal
            })

        # 4. Sequential Batch Runner
        background_tasks.add_task(run_sequential_tests, tasks_to_run, pipeline_ref=None)

        return {
            "status": "sequential_batch_started",
            "total_tasks": len(tasks_to_run),
            "message": "Tasks will run one by one. Check /tests for progress."
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Parsing Error: {str(e)}")
    
@app.post("/checking/{job_id}/trigger-all-tests")
async def trigger_all_tests(job_id: str, background_tasks: BackgroundTasks):
    if job_id not in CHECKING_JOBS:
        raise HTTPException(status_code=404)

    pipeline = CHECKING_JOBS[job_id]["pipeline"]
    all_tasks = []

    # Iterate through all Excel reports generated in Phase 2
    for msg in pipeline.ws_messages:
        if msg.get("type") == "url_report":
            session_id = msg["session_id"]
            url = msg["url"]
            
            report_path = os.path.join("semantic_test_output", f"test_report_{session_id}.xlsx")
            if os.path.exists(report_path):
                # Extract "EXPLORE" stories as Orchestrator goals
                df = pd.read_excel(report_path, sheet_name='Execution Plan', skiprows=13)
                for _, row in df.iterrows():
                    # steps = re.findall(r"'(.*?)'", str(row['Test Steps']))
                    steps = []
                    for line in str(row['Test Steps']).split('\n'):
                        line = line.strip()
                        if 'EXPLORE' in line:
                            cleaned = re.sub(r"^\d+\.\s*EXPLORE\s*'?", "", line).rstrip("'").strip()
                            if cleaned:
                                steps.append(cleaned)
                    if steps:
                        all_tasks.append({
                            "url": url,
                            "goal": f"Perform '{row['Feature / Context']}' workflow: " + " then ".join(steps)
                        })

    background_tasks.add_task(trigger_phase3_logic, all_tasks)
    return {"status": "batch_validation_started", "message": "Manual trigger successful.", "total_tasks": len(all_tasks)}

async def run_sequential_tests(tasks, pipeline_ref=None):

    print(f"🔄 Starting Sequential Batch for {len(tasks)} tasks...")
    
    if pipeline_ref:
        pipeline_ref.ws_messages.append({
            "type": "status", 
            "message": f"🚀 Phase 3: Batch Validation Started for {len(tasks)} stories"
        })

    print(f"🔄 Starting Sequential Batch for {len(tasks)} tasks...")
    
    for i, task in enumerate(tasks):
        msg = f"🚀 Launching Task {i+1}/{len(tasks)}: {task['goal'][:50]}..."
        print(f"🚀 {msg}")
        if pipeline_ref:
            pipeline_ref.ws_messages.append({"type": "status", "message": msg})
        
        # 1. Trigger the standard start_test function
        # This returns a StartTestResponse which contains the new test_id
        response = start_test(StartTestRequest(
            mode="whitebox",
            url=task["url"],
            goal=task["goal"]
        ))
        
        new_job_id = response.test_id

        if pipeline_ref:
            pipeline_ref.ws_messages.append({
                "type": "test_started",
                "test_id": new_job_id,
                "story_index": i + 1,
                "message": f"🧪 Test started with ID: {new_job_id}"
            })
        
        # 2. Wait for this specific job to finish
        is_finished = False
        while not is_finished:
            await asyncio.sleep(5) # Poll every 5 seconds
            
            # Check the status in the global registry
            current_status = TESTS.get(new_job_id, {}).get("status")
            
            if current_status in ["completed", "failed"]:
                print(f"✅ Task {i+1} finished with status: {current_status}")
                is_finished = True
            else:
                # Still running, continue waiting
                continue
        
        # 3. Small cool-down to ensure browser processes are fully cleaned up
        await asyncio.sleep(2)

    print("🏁 All sequential tasks in the batch have been processed.")


async def trigger_phase3_logic(pipeline):
    all_tasks = []
    for msg in pipeline.ws_messages:
        if msg.get("type") == "url_report":
            session_id = msg["session_id"]
            url = msg["url"]
            report_path = os.path.join("semantic_test_output", f"test_report_{session_id}.xlsx")
            
            if os.path.exists(report_path):
                df = pd.read_excel(report_path, sheet_name='Execution Plan', skiprows=13)
                for _, row in df.iterrows():
                    # steps = re.findall(r"'(.*?)'", str(row['Test Steps']))
                    steps = []
                    for line in str(row['Test Steps']).split('\n'):
                        line = line.strip()
                        if 'EXPLORE' in line:
                            cleaned = re.sub(r"^\d+\.\s*EXPLORE\s*'?", "", line).rstrip("'").strip()
                            if cleaned:
                                steps.append(cleaned)
                    if steps:
                        all_tasks.append({
                            "url": url,
                            "goal": f"Perform '{row['Feature / Context']}' workflow: " + " then ".join(steps)
                        })
    
    if all_tasks:
        # Launch the batch runner
        await run_sequential_tests(all_tasks, pipeline_ref=pipeline)
