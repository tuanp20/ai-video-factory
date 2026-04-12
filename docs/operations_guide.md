# 📖 AI Video Factory — Hướng Dẫn Vận Hành Server

> **Tài liệu bàn giao cho đội vận hành (Operations Guide)**
> Cập nhật: 2026-04-12

---

## Mục Lục

1. [Tổng Quan Hạ Tầng](#1-tổng-quan-hạ-tầng)
2. [Kết Nối SSH Vào Server](#2-kết-nối-ssh-vào-server)
3. [Kiến Trúc Container](#3-kiến-trúc-container)
4. [Lệnh Quản Lý Container](#4-lệnh-quản-lý-container)
5. [Deploy & Cập Nhật Code](#5-deploy--cập-nhật-code)
6. [Giám Sát (Monitoring) & Xem Logs](#6-giám-sát-monitoring--xem-logs)
7. [Nginx & SSL](#7-nginx--ssl)
8. [Biến Môi Trường (.env)](#8-biến-môi-trường-env)

---

## 1. Tổng Quan Hạ Tầng (ĐỘC LẬP)

> ⚠️ **Hệ thống này được thiết kế chạy trên một VPS độc lập hoàn toàn**, KHÔNG dùng chung với hệ thống Xưởng Media (để tránh nghẽn CPU/RAM do FFmpeg render video nặng).

### Server (Dedicated VPS)

| Thông tin | Giá trị |
|-----------|---------|
| **Cloud** | Mua mới 1 VPS riêng biệt (Vultr / DigitalOcean) |
| **VM IP** | *(Chờ cập nhật sau khi mua VPS)* |
| **OS** | Ubuntu 22.04 LTS hoặc 24.04 LTS |
| **User** | `root` hoặc `ubuntu` |
| **CPU/RAM** | Tối thiểu 2 CPU / 4GB RAM (Khuyến nghị 4 CPU/8G để Render) |

### Domain & Endpoints

| Mục đích | Domain | Port nội bộ |
|----------|--------|-------------|
| **Frontend/API** | `video.opabusiness.com` | `127.0.0.1:8000` |

### Cấu Trúc Thư Mục Trên Server

```
/opt/ai_video_factory/
├── .env                    # ⚠️ File secrets (Chứa key Plenxai, R2, Gemini)
├── Dockerfile              # Chỉ dẫn build FastAPI / Celery
├── requirements.txt        # Thư viện Python
├── infra/                  # 🟢 Container Ops
│   └── docker-compose.production.yml
├── scripts/                # 🟢 Deploy automation
│   └── deploy.sh
└── app/                    # Source code Python (FastAPI + Worker)
```

---

## 2. Kết Nối SSH Vào Server

Từ máy cá nhân (PowerShell/Terminal), sử dụng SSH Private Key:

```powershell
# Ví dụ thay 'root' bằng 'opc' hoặc 'ubuntu' tùy VPS
ssh -i "path/to/private.key" root@IP_CUA_BAN
```

---

## 3. Kiến Trúc Container

```
┌─────────────────────────── Server ──────────────────────────────┐
│                                                                 │
│   Nginx (80/443) ── Reverse Proxy + SSL                         │
│   └── video.opabusiness.com   → 127.0.0.1:8000 (Web API)      │
│                                                                 │
│   Docker Containers (Project: ai_video_factory_prod):           │
│   ┌─────────────────────────────────────────────────────────┐ │
│   │ 🌐 ai_video_factory_prod_web (FastAPI)       :8000      │ │
│   │ ⚙️ ai_video_factory_prod_worker (Celery)     (ngầm)     │ │
│   │ 📦 ai_video_factory_prod_redis (Redis Queue) :6379      │ │
│   └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**Vai trò:**
- `_web`: Xử lý HTTP request từ mảng React UI, tương tác Database SQLite.
- `_worker`: Chạy xử lý nền cho video (Cào tin, Editor TTS, Ghép FFmpeg).
- `_redis`: Hàng đợi Message Queue lưu trữ công việc chờ worker xử lý.

---

## 4. Lệnh Quản Lý Container

> **Làm việc tại thư mục code gốc trên server:** `cd /opt/ai_video_factory`

### 4.1 Xem trạng thái & Restart

```bash
# Xem các container đang chạy
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

# Khởi động lại toàn bộ stack production
export PROJECT_NAME=ai_video_factory_prod
docker compose -p $PROJECT_NAME -f infra/docker-compose.production.yml restart

# Restart một service cụ thể (vd: web hoặc worker)
docker restart ai_video_factory_prod_web
```

### 4.2 Xóa & Dọn dẹp

```bash
# Clear images & containers không sử dụng (Gỡ đầy ổ đĩa)
docker system prune -af
```

---

## 5. Deploy & Cập Nhật Code

Khi có code mới trên Github (nhánh `main`), bạn kết nối vào Server và chạy file script deploy tương tự chuẩn hệ thống cũ:

```bash
# 1. Đi tới thư mục dự án
cd /opt/ai_video_factory

# 2. Lấy code mới nhất
git pull origin main

# 3. Kích hoạt bộ script tự động thay mới container
bash scripts/deploy.sh /opt/ai_video_factory ai_video_factory_prod
```

Hệ thống sẽ chạy Build lại Image FastAPI (không downtime lâu), ngắt container cũ và gắn container mới.

---

## 6. Giám Sát (Monitoring) & Xem Logs

Hệ thống dùng driver logging chuẩn của Docker (có giới hạn file không bị phình to).

```bash
# Theo dõi trực tiếp log của WEB (FastAPI ngõ vào) (20 dòng)
docker logs ai_video_factory_prod_web --tail=20 -f

# Theo dõi trực tiếp log của WORKER (Lỗi render/FFmpeg/AI)
docker logs ai_video_factory_prod_worker --tail=50 -f

# Tìm kiếm lỗi "Error" trong Worker
docker logs ai_video_factory_prod_worker 2>&1 | grep -i "error"
```

---

## 7. Nginx & SSL

### Cấu hình chuẩn Nginx (File `/etc/nginx/sites-available/ai-video-factory`)

```nginx
server {
    listen 80;
    server_name video.opabusiness.com;

    # Cho phép upload file raw (lên đến 100MB)
    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Cấp SSL bằng Certbot

```bash
# Tạo chứng chỉ Let's Encrypt tự động
sudo certbot --nginx -d video.opabusiness.com

# Reload proxy
sudo nginx -t && sudo systemctl reload nginx
```

---

## 8. Biến Môi Trường (.env)

| Biến quan trọng | Chức năng | Nguy hiểm khi sai |
|-----------------|-----------|-------------------|
| `DATABASE_URL` | Lưu `sqlite:///./ai_video_factory.db` | Mất quyền admin |
| `PLENXAI_API_KEY` | Tạo video Kling/Runway | Worker báo lỗi AI limit |
| `GEMINI_API_KEY` | Prompt text via Gemini | Hệ thống scraper cào báo tịt ngòi |
| `R2_ACCESS_KEY` / `R2_SECRET_KEY` | Đăng video Cloudflare R2 | Upload video thất bại |

**Chỉnh sửa env thủ công trên server:**
```bash
nano /opt/ai_video_factory/.env
# Sau khi lưu, KHÔNG CẦN BUILD lại, chỉ cần Restart
docker compose -p ai_video_factory_prod -f infra/docker-compose.production.yml restart
```

---

## 9. CI/CD Pipeline (Deploy Tự Động)

Hệ thống có cấu hình **GitHub Actions** tại file `.github/workflows/deploy.yml`. Tự động rsync code lên VPS Độc Lập khi push vào nhánh `main`.

### Cài đặt GitHub Secrets
Truy cập GitHub Repo $\rightarrow$ **Settings** $\rightarrow$ **Secrets and variables** $\rightarrow$ **Actions**:

| Tên Secret | Chức năng (Dành cho VPS Độc lập) |
|------------|----------------------------------|
| `VIDEO_VPS_HOST` | Địa chỉ IP của VPS mới |
| `VIDEO_VPS_USER` | `root` hoặc `ubuntu` |
| `VIDEO_VPS_SSH_KEY` | Private Key để SSH vào VPS này |
| `PROD_R2_ACCESS_KEY` | (Các key Cloudflare, Plenxai tương ứng) |
