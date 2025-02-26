FROM python:3.10-slim

WORKDIR /app

# ติดตั้ง Node.js และ npm
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g wscat \
    # ลบแคชและไฟล์ที่ไม่จำเป็นเพื่อลดขนาด image
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]