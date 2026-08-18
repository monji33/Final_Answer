FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y python3.8 python3-pip && \
    apt-get clean

WORKDIR /app

CMD ["tail", "-f", "/dev/null"]