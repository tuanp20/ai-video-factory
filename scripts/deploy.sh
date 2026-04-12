#!/bin/bash
# Script deploy tự động cho AI Video Factory (tương tự chuẩn Xưởng Media)
# Sử dụng: bash scripts/deploy.sh <PROJECT_PATH> <PROJECT_NAME>
# Ví dụ: bash scripts/deploy.sh /opt/ai_video_factory ai_video_factory_prod

PROJECT_PATH=$1
PROJECT_NAME=$2

if [ -z "$PROJECT_PATH" ] || [ -z "$PROJECT_NAME" ]; then
  echo "❌ Lỗi: Thiếu tham số."
  echo "Sử dụng: bash scripts/deploy.sh <PROJECT_PATH> <PROJECT_NAME>"
  exit 1
fi

echo "🚀 Bắt đầu quá trình deploy cho project: $PROJECT_NAME tại $PROJECT_PATH"

cd $PROJECT_PATH || { echo "❌ Lỗi: Không tìm thấy thư mục $PROJECT_PATH"; exit 1; }

# 1. Kéo code mới nhất (nếu chạy git trực tiếp trên server)
# git pull origin main

# 2. Xây dựng lại images (không dùng bộ đệm cũ để đảm bảo code mới nhất)
echo "📦 Đang build mới Docker Images..."
docker compose -p $PROJECT_NAME -f infra/docker-compose.production.yml build

# 3. Khởi động lại các container (force recreate để áp dụng image mới)
echo "🔄 Xóa container cũ và khởi chạy container mới..."
docker compose -p $PROJECT_NAME -f infra/docker-compose.production.yml up -d --force-recreate --remove-orphans

# 4. Kiểm tra sức khỏe (Health Check Fast API)
echo "⏳ Đang chờ hệ thống khởi động..."
sleep 5
echo "✅ Trạng thái các container:"
docker ps --filter "name=${PROJECT_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo "🎉 Deploy hoàn tất!"
