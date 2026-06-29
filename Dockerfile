FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    ca-certificates git python3 python3-pip curl \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22 для OmniRoute
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs

# OmniRoute
RUN npm install -g omniroute

# Python deps
RUN pip3 install flask requests edge-tts aliens-eye --break-system-packages

# Metalogos
COPY bin/mlog /usr/local/bin/mlog
RUN chmod +x /usr/local/bin/mlog

WORKDIR /office
COPY entrypoint.sh /office/entrypoint.sh
RUN chmod +x /office/entrypoint.sh
COPY . .
RUN mkdir -p /office/data /tmp
RUN git config --global user.email "agent@fosved.office" \
    && git config --global user.name "Fosved Agent"

EXPOSE 10000

CMD ["bash", "entrypoint.sh"]
