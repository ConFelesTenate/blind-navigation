# Streamlit Pedestrian Nav (`streamlit-pedestrian-nav`) 🚶🇻🇳

Thư viện hệ thống dẫn đường người đi bộ tích hợp giọng nói tiếng Việt và nhận diện đèn giao thông thời gian thực dành cho người khiếm thị.

---

- Dẫn đường & Đầu vào giọng nói tiếng Việt (`vi-VN`): Tích hợp Web Speech API cho phép nói điểm đến bằng tiếng Việt và nhận hướng dẫn giọng nói.
-  Nhận diện Đèn Giao Thông qua Camera: Mô hình YOLO phát hiện trạng thái đèn giao thông (Đỏ, Vàng, Xanh) theo thời gian thực và phát âm thanh/rung phản hồi cảnh báo người dùng.
- La bàn 3D khi cầm dọc điện thoại: Thuật toán ma trận xoay 3D giúp la bàn chỉ hướng chính xác khi cầm điện thoại đi bộ trên đường.
- Tự động mở Cloudflare HTTPS Tunnel: Tự động sinh đường dẫn HTTPS an toàn để trình duyệt di động (iOS Safari / Android Chrome).
- Tự động ưu tiên kết nối máy chủ OSRM Docker nội bộ hoặc tự động chuyển sang máy chủ OSRM public khi không có container local.

---

Python Version: Python 3.9+

 Cloudflared Tunnel [https://github.com/cloudflare/cloudflared/releases/latest](https://github.com/cloudflare/cloudflared/releases/latest):
   * **Windows (64-bit)**: Download `cloudflared-windows-amd64.exe`.
   * **macOS (Apple Silicon)**: Download `cloudflared-darwin-arm64`.
   * **Linux (x86_64)**: Download `cloudflared-linux-amd64`.
