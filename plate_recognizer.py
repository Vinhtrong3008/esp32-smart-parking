"""Quét biển số từ khung hình của camera dùng chung. Model CHỈ chạy khi hàm read() được gọi (lúc cảm biến báo có xe).
Tương thích open-image-models 0.6.x và fast-plate-ocr 1.1.x."""
import re
import time
import warnings
from collections import Counter

import cv2

warnings.filterwarnings("ignore", category=DeprecationWarning)

DETECTOR_MODEL = "yolo-v9-t-384-license-plate-end2end"
OCR_MODEL = "cct-xs-v1-global-model"


class PlateRecognizer:
    def __init__(self, max_frames=12, timeout=6.0, min_votes=2):
        self.max_frames = max_frames
        self.timeout = timeout
        self.min_votes = min_votes

        import open_image_models as oim
        from fast_plate_ocr import LicensePlateRecognizer

        if hasattr(oim, "create_detector"):
            self.detector = oim.create_detector(DETECTOR_MODEL)
        else:  # bản cũ
            self.detector = oim.LicensePlateDetector(detection_model=DETECTOR_MODEL)
        self.ocr = LicensePlateRecognizer(OCR_MODEL)

    @staticmethod
    def _normalize(text):
        text = re.sub(r"[^A-Z0-9]", "", str(text).upper())
        return text if 6 <= len(text) <= 10 else None

    def _read_frame(self, frame):
        h, w = frame.shape[:2]
        plates = []
        for det in self.detector.predict(frame):
            b = det.bounding_box
            crop = frame[max(b.y1, 0):min(b.y2, h), max(b.x1, 0):min(b.x2, w)]
            if crop.size == 0:
                continue
            rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)  # model OCR cần ảnh RGB 3 kênh
            pred = self.ocr.run(rgb)[0]
            plate = self._normalize(getattr(pred, "plate", pred))
            if plate:
                plates.append(plate)
        return plates

    def read(self, camera):
        """Lấy các khung hình mới liên tiếp từ camera, đọc biển, bỏ phiếu.
        Trả về (biển_số, khung_hình) hoặc (None, khung_hình_cuối)."""
        votes, best_frame, last_frame, seen = Counter(), {}, None, None
        start, n = time.time(), 0
        while n < self.max_frames and time.time() - start < self.timeout:
            frame = camera.latest()
            if frame is None or frame is seen:  # chưa có khung mới
                time.sleep(0.03)
                continue
            seen = last_frame = frame
            n += 1
            for p in self._read_frame(frame):
                votes[p] += 1
                best_frame[p] = frame
        if votes:
            plate, count = votes.most_common(1)[0]
            if count >= self.min_votes:
                return plate, best_frame[plate]
        return None, last_frame
