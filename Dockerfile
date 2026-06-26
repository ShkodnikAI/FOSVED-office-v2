FROM ubuntu:24.04
RUN apt-get update && apt-get install -y ca-certificates git python3 python3-pip curl && rm -rf /var/lib/apt/lists/*
RUN pip3 install flask requests edge-tts --break-system-packages
WORKDIR /office
COPY entrypoint.sh /office/entrypoint.sh
RUN chmod +x /office/entrypoint.sh
ENV DEPLOY_SHA=964bbd9b9be2f41c39c8540c785f1d331073323d
COPY . .
RUN mkdir -p /office/data /tmp
RUN git config --global user.email "agent@fosved.office" && git config --global user.name "Fosved Agent"
COPY bin/mlog /usr/local/bin/mlog
RUN chmod +x /usr/local/bin/mlog
EXPOSE 10000
CMD ["bash", "entrypoint.sh"]
