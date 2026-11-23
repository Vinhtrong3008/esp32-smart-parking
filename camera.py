"""Webcam chạy nền liên tục: cấp khung hình cho dashboard (live view) và cho model quét biển khi cần.
Chỉ MỘT nơi mở webcam, nên live view và quét biển dùng chung, không tranh nhau thiết bị."""
import sys
import threading
import time

import cv2
import numpy as np


class Camera:
    def __init__(self, index=0, width=640, height=480):
        self.width, self.height = width, height
        self._wanted = int(index)
        self._frame = None
        self._lock = threading.Lock()
        self._info = {"ok": False, "index": self._wanted, "backend": None, "size": None}

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    # ---- điều khiển / trạng thái ----
    def set_index(self, index):
        """Đổi sang camera khác (0, 1, 2...). Luồng nền sẽ tự mở lại."""
        self._wanted = int(index)

    def status(self):
        with self._lock:
            return dict(self._info)

    def _set_info(self, **kw):
        with self._lock:
            self._info.update(kw)
            if not kw.get("ok", True):
                self._frame = None

    # ---- bên trong ----
    def _open(self, index):
        if sys.platform == "win32":
            backends = [("DSHOW", cv2.CAP_DSHOW), ("MSMF", cv2.CAP_MSMF), ("ANY", cv2.CAP_ANY)]
        else:
            backends = [("ANY", cv2.CAP_ANY)]
        for name, api in backends:
            cap = cv2.VideoCapture(index, api)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                ok, frame = cap.read()
                if ok:
                    return cap, name, f"{frame.shape[1]}x{frame.shape[0]}"
            cap.release()
        return None, None, None

    def _loop(self):
        cap, opened = None, None
        while True:
            if cap is not None and opened != self._wanted:  # người dùng đổi camera
                cap.release()
                cap = None
            if cap is None:
                idx = self._wanted
                cap, backend, size = self._open(idx)
                if cap is None:
                    self._set_info(ok=False, index=idx, backend=None, size=None)
                    time.sleep(2)  # chưa mở được: thử lại sau 2 giây
                    continue
                opened = idx
                self._set_info(ok=True, index=idx, backend=backend, size=size)
            ok, frame = cap.read()
            if not ok:  # cam bị rút/lỗi: mở lại
                cap.release()
                cap = None
                self._set_info(ok=False, backend=None, size=None)
                continue
            with self._lock:
                self._frame = frame

    def latest(self):
        """Khung hình mới nhất (BGR) hoặc None nếu cam chưa sẵn sàng."""
        with self._lock:
            return self._frame

    def mjpeg(self, fps=15):
        """Generator MJPEG cho thẻ <img src="/api/stream">."""
        placeholder = np.zeros((self.height, self.width, 3), np.uint8)
        cv2.putText(placeholder, "KHONG CO TIN HIEU CAMERA", (60, self.height // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        while True:
            frame = self.latest()
            ok, buf = cv2.imencode(".jpg", frame if frame is not None else placeholder,
                                   [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
            time.sleep(1 / fps)
