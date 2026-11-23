# Smart Parking - Bãi đỗ xe thông minh

Hệ thống quản lý bãi đỗ xe sử dụng camera nhận diện biển số, ESP32, cảm biến siêu âm và thanh chắn servo.

## Tính năng

- Nhận diện biển số bằng camera và AI.
- Tự động xác định xe vào hoặc xe ra.
- Điều khiển thanh chắn bằng ESP32.
- Dashboard theo dõi trạng thái bãi xe theo thời gian thực.
- Lưu lịch sử xe vào/ra bằng SQLite.
- Lưu ảnh chụp khi nhận diện biển số.
- Giả lập sự kiện không cần ESP32 để kiểm thử.
- Hỗ trợ chọn nhiều camera.

## Cấu trúc dự án

```text
final iot/
├── app.py                       # FastAPI server và API
├── camera.py                    # Quản lý camera và luồng MJPEG
├── plate_recognizer.py          # Phát hiện và đọc biển số
├── parking.db                   # Cơ sở dữ liệu SQLite
├── requirements.txt             # Thư viện Python
├── static/
│   ├── index.html               # Giao diện dashboard
│   └── snaps/                   # Ảnh chụp khi nhận diện
└── parking_gate/
    └── parking_gate.ino         # Firmware cho ESP32
```

## Yêu cầu

### Phần mềm

- Python 3.10 trở lên
- Arduino IDE
- ESP32 Board Package
- Webcam hoặc camera USB

### Phần cứng

- ESP32
- 2 cảm biến siêu âm HC-SR04
- Servo điều khiển thanh chắn
- LCD I2C 16x2
- Camera

## Cài đặt backend

Mở PowerShell tại thư mục dự án:

```powershell
cd "D:\final iot"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Chạy server

```powershell
uvicorn app:app --host 0.0.0.0 --port 8000
```

Mở dashboard tại:

```text
http://localhost:8000
```

Để truy cập từ thiết bị khác trong cùng mạng:

```text
http://<IP_MAY_CHAY_SERVER>:8000
```

## Cấu hình camera

Mặc định hệ thống sử dụng camera số `0`. Có thể chọn camera trên dashboard hoặc cấu hình bằng biến môi trường:

```powershell
$env:CAMERA_INDEX="1"
uvicorn app:app --host 0.0.0.0 --port 8000
```

Camera được mở bởi một luồng nền duy nhất và dùng chung cho hình ảnh trực tiếp và nhận diện biển số.

## Cấu hình ESP32

Mở file `parking_gate/parking_gate.ino` và cập nhật Wi-Fi cùng địa chỉ máy chạy server:

```cpp
const char* WIFI_SSID = "TEN_WIFI";
const char* WIFI_PASS = "MAT_KHAU_WIFI";
const char* SERVER_BASE = "http://IP_MAY_CHAY_SERVER:8000";
```

Không đưa thông tin Wi-Fi thật vào kho mã công khai.

### Sơ đồ chân

| Thiết bị | Chân ESP32 |
|---|---:|
| Cảm biến vào - TRIG | GPIO 32 |
| Cảm biến vào - ECHO | GPIO 14 |
| Cảm biến ra - TRIG | GPIO 33 |
| Cảm biến ra - ECHO | GPIO 27 |
| Servo | GPIO 13 |
| LCD SDA | GPIO 25 |
| LCD SCL | GPIO 26 |
| LCD I2C | `0x27` |

### Thư viện Arduino

- ArduinoJson
- ESP32Servo
- LiquidCrystal_I2C

Sau khi cấu hình:

1. Kết nối ESP32 với máy tính.
2. Chọn đúng board ESP32 và cổng COM.
3. Nạp file `parking_gate.ino`.
4. Đảm bảo ESP32 và máy chạy server cùng mạng Wi-Fi.

## Nguyên lý hoạt động

1. Cảm biến siêu âm phát hiện xe.
2. ESP32 gửi yêu cầu đến API `/api/gate-event`.
3. Server lấy nhiều khung hình từ camera.
4. Model phát hiện và đọc biển số.
5. Hệ thống kiểm tra trạng thái xe trong cơ sở dữ liệu.
6. Server trả kết quả cho ESP32.
7. Nếu được phép, servo mở thanh chắn.
8. Thanh chắn tự đóng sau khi xe đi qua.

## API

### Kiểm tra trạng thái

```http
GET /api/status
```

### Gửi sự kiện từ ESP32

```http
POST /api/gate-event
Content-Type: application/json
```

```json
{
  "gate": "auto",
  "sensor": "in"
}
```

### Giả lập sự kiện

```http
POST /api/simulate
Content-Type: application/json
```

```json
{
  "gate": "auto",
  "plate": "51A12345"
}
```

Để trống `plate` hoặc đặt giá trị `null` để nhận diện bằng camera thật.

### Các endpoint khác

| Phương thức | Endpoint | Mô tả |
|---|---|---|
| GET | `/api/stream` | Luồng camera MJPEG |
| POST | `/api/camera` | Đổi camera |
| GET | `/api/sessions?limit=50` | Xem lịch sử phiên gửi xe |

## Quy tắc xác định xe vào/ra

Ở chế độ `gate: "auto"`:

- Biển số chưa có trong bãi: xác định là xe vào.
- Biển số đang có trong bãi: xác định là xe ra.
- Xe vào khi bãi đầy: từ chối.
- Xe ra nhưng không tồn tại trong bãi: từ chối.

Sức chứa mặc định là 10 xe và được cấu hình bằng `MAX_SLOTS` trong `app.py`.

## Xử lý sự cố

### Không mở được camera

- Đóng các ứng dụng khác đang sử dụng camera.
- Thử chọn camera khác trên dashboard.
- Kiểm tra biến môi trường `CAMERA_INDEX`.
- Kiểm tra quyền truy cập camera của Python.

### ESP32 không kết nối được server

- Kiểm tra ESP32 và máy chủ có cùng mạng Wi-Fi.
- Kiểm tra địa chỉ IP trong `SERVER_BASE`.
- Kiểm tra firewall của Windows.
- Mở thử `http://<IP_SERVER>:8000/api/status` trên thiết bị khác.

### Không nhận diện được biển số

- Đảm bảo biển số đủ sáng và nằm rõ trong khung hình.
- Đặt camera gần khu vực thanh chắn.
- Giảm tốc độ xe khi đi qua camera.
- Kiểm tra các model AI đã được cài đặt đầy đủ.

## Lưu ý bảo mật

- Không công khai thông tin Wi-Fi trong mã nguồn.
- Không mở server ra Internet nếu chưa có xác thực.
- `parking.db` và `static/snaps` có thể chứa dữ liệu nhạy cảm.

## Công nghệ sử dụng

- Python, FastAPI, Uvicorn
- OpenCV
- SQLite
- Open Image Models
- Fast Plate OCR
- ESP32 và Arduino
- HTML, CSS, JavaScript
