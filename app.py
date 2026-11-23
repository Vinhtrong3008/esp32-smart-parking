"""Server bãi đỗ xe: nhận sự kiện từ ESP32 -> nhận diện biển số -> trả lệnh mở/không mở + dashboard theo dõi."""
import os
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from camera import Camera
from plate_recognizer import PlateRecognizer

BASE = Path(__file__).parent
DB_PATH = BASE / "parking.db"
SNAP_DIR = BASE / "static" / "snaps"
SNAP_DIR.mkdir(parents=True, exist_ok=True)
MAX_SLOTS = 10  # sức chứa tối đa của bãi, sửa theo thực tế

app = FastAPI(title="Smart Parking")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
camera = Camera(index=os.getenv("CAMERA_INDEX", "0")).start()  # webcam chạy nền liên tục để xem live; đổi trên dashboard hoặc set CAMERA_INDEX
recognizer = PlateRecognizer()
state = {"scanning": False}
lock = threading.Lock()  # chỉ xử lý 1 sự kiện tại một thời điểm (1 camera, 1 cổng)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


with db() as c:
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate TEXT NOT NULL,
            time_in TEXT NOT NULL,
            time_out TEXT);
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL,
            gate TEXT NOT NULL,
            plate TEXT,
            allowed INTEGER NOT NULL,
            message TEXT,
            image TEXT);
        """
    )


class GateEvent(BaseModel):
    gate: str = "auto"  # "auto" (mặc định): tự suy ra vào/ra theo biển số; "in"/"out": ép hướng (chỉ để test)
    sensor: Optional[str] = None  # cảm biến nào báo có xe ("in"/"out"), chỉ dùng để ghi log


class CameraSelect(BaseModel):
    index: int


class SimulateEvent(BaseModel):
    gate: str = "auto"
    plate: Optional[str] = None  # nếu để trống sẽ dùng webcam như thật


def decide(c, gate, plate, now):
    """Trả về (cho_phép, dòng1, dòng2, hướng_đã_xác_định).
    gate="auto": biển chưa có trong bãi -> XE VÀO; biển đang có trong bãi -> XE RA."""
    inside = c.execute("SELECT * FROM sessions WHERE plate=? AND time_out IS NULL", (plate,)).fetchone()
    if gate == "auto":
        gate = "out" if inside else "in"
    if gate == "in":
        if inside:
            return False, plate, "Xe da o trong", "in"
        count = c.execute("SELECT COUNT(*) FROM sessions WHERE time_out IS NULL").fetchone()[0]
        if count >= MAX_SLOTS:
            return False, "Bai da day", plate, "in"
        c.execute("INSERT INTO sessions(plate, time_in) VALUES (?, ?)", (plate, now.isoformat()))
        return True, "XE VAO", plate, "in"
    if gate == "out":
        if not inside:
            return False, plate, "Khong co trong bai", "out"
        c.execute("UPDATE sessions SET time_out=? WHERE id=?", (now.isoformat(), inside["id"]))
        minutes = int((now - datetime.fromisoformat(inside["time_in"])).total_seconds() // 60)
        return True, "XE RA " + plate, f"Da do {minutes} phut", "out"
    return False, "Su kien sai", "", gate


def process(gate, forced_plate=None, sensor=None):
    with lock:
        now = datetime.now()
        frame = None
        plate = re.sub(r"[^A-Z0-9]", "", forced_plate.upper()) if forced_plate else None
        print(f"[SENSOR] cam bien {sensor or '-'} bao co xe: " + (f"dung bien nhap tay {plate}" if plate else "bat dau goi model quet bien so"), flush=True)
        if not plate:
            state["scanning"] = True
            try:
                plate, frame = recognizer.read(camera)  # model chỉ chạy tại đây
            finally:
                state["scanning"] = False

        image = None
        if frame is not None:
            name = f"{now:%Y%m%d_%H%M%S}.jpg"
            cv2.imwrite(str(SNAP_DIR / name), frame)
            image = f"/static/snaps/{name}"

        with db() as c:
            if not plate:
                allowed, l1, l2 = False, "Khong doc duoc", "bien so"
            else:
                allowed, l1, l2, gate = decide(c, gate, plate, now)
            c.execute(
                "INSERT INTO events(time, gate, plate, allowed, message, image) VALUES (?,?,?,?,?,?)",
                (now.isoformat(timespec="seconds"), gate, plate, int(allowed), f"{l1} | {l2}", image),
            )
        print(f"[RESULT] plate={plate} huong={gate} open={allowed} ({l1} | {l2})", flush=True)
        return {"open": allowed, "line1": l1[:16], "line2": l2[:16], "plate": plate, "gate": gate, "image": image}


# ---------- API cho ESP32 ----------
@app.post("/api/gate-event")
def gate_event(ev: GateEvent):
    return process(ev.gate, sensor=ev.sensor)


# ---------- API cho dashboard ----------
@app.post("/api/simulate")
def simulate(ev: SimulateEvent):
    """Chỉ dùng để TEST: giả lập xe vào/ra mà không cần ESP32 (có thể gõ tay biển số)."""
    return process(ev.gate, ev.plate, sensor="mo phong")


@app.get("/api/status")
def status():
    with db() as c:
        inside = c.execute("SELECT plate, time_in FROM sessions WHERE time_out IS NULL ORDER BY id DESC").fetchall()
        events = c.execute("SELECT * FROM events ORDER BY id DESC LIMIT 30").fetchall()
        today = datetime.now().strftime("%Y-%m-%d")
        n_in = c.execute("SELECT COUNT(*) FROM events WHERE gate='in' AND allowed=1 AND time LIKE ?", (today + "%",)).fetchone()[0]
        n_out = c.execute("SELECT COUNT(*) FROM events WHERE gate='out' AND allowed=1 AND time LIKE ?", (today + "%",)).fetchone()[0]
    return {
        "scanning": state["scanning"],
        "camera": camera.status(),
        "capacity": MAX_SLOTS,
        "occupied": len(inside),
        "today_in": n_in,
        "today_out": n_out,
        "inside": [dict(r) for r in inside],
        "events": [dict(r) for r in events],
    }


@app.post("/api/camera")
def select_camera(sel: CameraSelect):
    camera.set_index(sel.index)
    return {"requested": sel.index}


@app.get("/api/stream")
def stream():
    """Live view webcam cho dashboard (MJPEG)."""
    return StreamingResponse(camera.mjpeg(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/sessions")
def sessions(limit: int = 50):
    with db() as c:
        rows = c.execute("SELECT * FROM sessions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/")
def dashboard():
    return FileResponse(BASE / "static" / "index.html")
