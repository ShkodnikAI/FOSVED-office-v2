FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    ca-certificates git python3 python3-pip curl nodejs npm \
    tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-jpn tesseract-ocr-kor \
    && rm -rf /var/lib/apt/lists/*

# Python deps
RUN pip3 install flask requests edge-tts aliens-eye pymupdf openpyxl cryptography --break-system-packages

# Metalogos v0.12.0 — WH-1: force cache invalidation to ensure latest binary
COPY bin/mlog /usr/local/bin/mlog
RUN chmod +x /usr/local/bin/mlog && /usr/local/bin/mlog --version

WORKDIR /office
COPY entrypoint.sh /office/entrypoint.sh
RUN chmod +x /office/entrypoint.sh
COPY . .

# Node.js deps (Prisma client for PostgreSQL)
RUN npm install --production 2>/dev/null || true
RUN npx prisma generate 2>/dev/null || true

RUN mkdir -p /office/data /tmp
RUN git config --global user.email "agent@fosved.office" \
    && git config --global user.name "Fosved Agent"

EXPOSE 10000

CMD ["bash", "entrypoint.sh"]
