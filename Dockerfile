FROM ubuntu:24.04
RUN apt-get update && apt-get install -y ca-certificates git python3 python3-pip curl && rm -rf /var/lib/apt/lists/*
RUN pip3 install flask requests edge-tts --break-system-packages

WORKDIR /office

# ── Source code FIRST — any file change invalidates ALL layers below ──
# This is the cache-bust guarantee: Docker compares file checksums of COPY
COPY app.mlog /office/app.mlog
COPY llm_proxy.py /office/llm_proxy.py
COPY reverse_proxy.py /office/reverse_proxy.py
COPY entrypoint.sh /office/entrypoint.sh
COPY dept/ /office/dept/
COPY library/ /office/library/
COPY miniapp/ /office/miniapp/
COPY upload/ /office/upload/

RUN chmod +x /office/entrypoint.sh

# Binary last — rarely changes
COPY bin/mlog /usr/local/bin/mlog
RUN chmod +x /usr/local/bin/mlog

RUN mkdir -p /office/data /tmp
RUN git config --global user.email "agent@fosved.office" && git config --global user.name "Fosved Agent"

EXPOSE 10000
CMD ["bash", "entrypoint.sh"]