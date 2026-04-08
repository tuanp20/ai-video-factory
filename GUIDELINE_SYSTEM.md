Dưới đây là Tài liệu Hướng dẫn Triển khai (Deployment Guideline) chuẩn mực, được trình bày dưới dạng tài liệu kỹ thuật chuyên nghiệp. Bạn có thể sao chép nguyên văn tài liệu này để bàn giao cho đội ngũ Dev, quản lý dự án hoặc đối tác kỹ thuật.

───

TÀI LIỆU BÀN GIAO & TRIỂN KHAI: HỆ THỐNG AI VIDEO FACTORY

1. TỔNG QUAN HỆ THỐNG (SYSTEM OVERVIEW)

AI Video Factory là một nền tảng SaaS nội bộ (Self-hosted) chuyên dụng để sản xuất video AI hàng loạt. Hệ thống loại bỏ hoàn toàn các công cụ no-code trung gian (như n8n, Make), sử dụng kiến trúc Full-Code (100% Python) để tối đa hóa hiệu năng, giữ nguyên chất lượng gốc của file media, và thiết kế theo dạng Module hóa nhằm chống phụ thuộc vào một nhà cung cấp AI duy nhất (Vendor Lock-in).

Công nghệ lõi (Tech Stack):

• Backend & Frontend Web: Python FastAPI + Jinja2 (TailwindCSS).
• Message Queue (Hàng đợi): Redis + Celery.
• Cloud Storage: Cloudflare R2 (thông qua AWS Boto3).
• Post-Production (Hậu kỳ): FFmpeg + Edge-TTS (Microsoft).
• Database (Quản trị): SQLite.

───

2. KIẾN TRÚC VÀ LUỒNG HOẠT ĐỘNG (THE PIPELINE)

Hệ thống vận hành theo chuỗi 5 giai đoạn (Phase 0 -> 4) hoàn toàn khép kín:

• Giai đoạn 0: Săn nội dung (Data Scraper)
• Nhiệm vụ: Người dùng nhập URL báo chí hoặc Từ khóa.
• Logic: Dùng thư viện Trafilatura bóc tách văn bản. Đưa qua LLM (Gemini/OpenAI) tóm tắt, tự động sinh Kịch bản TTS và Prompt tạo Video.
• Giai đoạn 1: Khởi tạo dữ liệu (Ingestion)
• Nhiệm vụ: Nơi nhân sự tải ảnh/nguyên liệu lên.
• Logic: Ảnh gốc chất lượng cao được tải thẳng từ giao diện lên Cloudflare R2 thông qua boto3. Trả về Direct URL (Public) ghép vào JSON Payload chung.
• Giai đoạn 2: Điều phối tiến trình (Orchestration)
• Nhiệm vụ: Quản lý luồng chạy ngầm, không làm treo server.
• Logic: FastAPI nhận JSON Payload $\rightarrow$ đẩy vào hàng đợi Redis. Các công nhân Celery Worker chạy nền sẽ tuần tự lấy Task ra để xử lý. Có cơ chế Auto-Retry khi lỗi mạng.
• Giai đoạn 3: Render Video AI (Generation Core)
• Nhiệm vụ: Gọi API của hãng thứ 3 để tạo video.
• Logic: Sử dụng Adapter Pattern (Lớp trừu tượng). Luồng chính chỉ truyền data vào VideoProvider. Tùy cấu hình, nó sẽ rẽ nhánh gọi API Plenxai, Kling hoặc Runway. (Sửa/Thêm hãng mới không ảnh hưởng code chính).
• Giai đoạn 4: Hậu kỳ & Quality Gate
• Nhiệm vụ: Ghép video, tạo giọng đọc và Kiểm duyệt.
• Logic:

1. Celery gọi edge-tts sinh file Audio.
2. Gọi FFmpeg ghép nối các đoạn Video, chèn Audio, đóng Watermark.
3. Tải Video hoàn thiện lên R2, ghi log vào database SQLite với trạng thái Pending_Review.
4. Trưởng nhóm vào trang Admin duyệt (Approve) $\rightarrow$ Kích hoạt API đăng thẳng lên TikTok/Shorts.

───

3. YÊU CẦU MÔI TRƯỜNG & HẠ TẦNG (INFRASTRUCTURE)

Để triển khai thực tế (Production), cần chuẩn bị:

1. Máy chủ (VPS):

• Cấu hình tối thiểu: 2 Core CPU, 4GB RAM, 50GB SSD (Khuyên dùng Ubuntu 22.04 LTS).

2. Các phần mềm cấp Hệ điều hành (Bắt buộc cài trước):

• Python 3.10+ và pip.
• FFmpeg: Cài đặt toàn cục trên OS (sudo apt install ffmpeg).
• Redis-Server: Hàng đợi tin nhắn (sudo apt install redis-server hoặc chạy qua Docker).
• Process Manager: Cài PM2 hoặc cấu hình Systemd để treo FastAPI và Celery chạy 24/7.

3. Dịch vụ bên thứ 3 (API Keys):

• Tài khoản Cloudflare R2 (Lấy Account ID, Access Key, Secret Key).
• API Key của Plenxai (Developer API).
• API Key LLM (Gemini 1.5 Flash / OpenAI).

───

4. CẤU TRÚC MÃ NGUỒN (SOURCE CODE STRUCTURE)

Toàn bộ source code nằm tại thư mục dự án ai_video_factory:

ai_video_factory/
├── .env # Chứa các API Key và cấu hình bảo mật
├── requirements.txt # Danh sách thư viện Python
└── app/
├── main.py # File khởi chạy FastAPI (Cổng giao tiếp chính)
├── core/
│ └── config.py # Class load cấu hình từ file .env
├── templates/
│ └── index.html # Giao diện Frontend nội bộ (TailwindCSS)
├── services/
│ ├── scraper.py # Module cào báo & LLM Prompting
│ ├── storage.py # Module AWS Boto3 thao tác với R2
│ ├── video_provider.py # Các Class Adapter kết nối Plenxai/Kling
│ └── editor.py # Module gọi edge-TTS và FFmpeg
└── worker/
└── tasks.py # Nhiệm vụ Background chạy trên Celery

───

5. HƯỚNG DẪN CÀI ĐẶT & CHẠY DỰ ÁN (QUICK START)

Bước 1: Clone và Cài thư viện Python

cd ai_video_factory
pip install -r requirements.txt

Bước 2: Cấu hình biến môi trường
Mở file .env và điền chính xác các thông tin Cloudflare R2 và Plenxai API.

Bước 3: Khởi động hệ thống (Chạy Local hoặc trên VPS)
Cần mở 2 tiến trình (Terminal) chạy song song:

Tiến trình 1: Khởi động Web Server (FastAPI)

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

(Lúc này có thể truy cập http://localhost:8000 để mở giao diện nội bộ).

Tiến trình 2: Khởi động Celery Worker (Công nhân xử lý video)

# Trên Linux:

celery -A app.worker.tasks worker --loglevel=info

# Trên Windows (cần thư viện gevent):

celery -A app.worker.tasks worker --loglevel=info -P gevent

───

6. HƯỚNG DẪN MỞ RỘNG (SCALING & EXTENDING)

• Thêm nhà cung cấp AI mới:
Chỉ cần mở file app/services/video_provider.py. Tạo một Class mới kế thừa từ VideoProvider (Ví dụ: class RunwayAdapter(VideoProvider):). Viết logic API gọi sang Runway vào đó. Code lõi hệ thống tự động tương thích mà không bị gãy form nhập liệu.
• Scale Up (Quá tải VPS):
Khi dự án đạt mức render 1000 video/ngày, VPS chính sẽ bị quá tải CPU do FFmpeg. Giải pháp: Mua thêm VPS số 2, số 3. Trỏ cấu hình REDIS_URL của các con VPS mới về IP của VPS chính và chỉ việc chạy lệnh khởi động celery worker. Task sẽ tự động chia đều cho các VPS.
