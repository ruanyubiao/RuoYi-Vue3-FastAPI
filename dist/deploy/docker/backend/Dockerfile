# PGT backend shell: Python 3.13 (Linux) with every dependency of the pgt wheel,
# except pgt itself, TeleMetryParser and gpcan. Those three wheels are mounted at /opt/pgt/whl
# and installed by entrypoint.sh when the container starts.
# Built by docker_image_backend_build.bat (it writes requirements.txt next to this file).
FROM python:3.13-slim

ARG PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai \
    PGT_DATA_DIR=/opt/pgt/data

# time zone data, so log times follow TZ
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
 && apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /opt/pgt/requirements.txt
RUN pip install --no-cache-dir -i ${PIP_INDEX} -r /opt/pgt/requirements.txt

COPY entrypoint.sh /opt/pgt/entrypoint.sh
RUN sed -i 's/\r$//' /opt/pgt/entrypoint.sh \
 && chmod +x /opt/pgt/entrypoint.sh \
 && mkdir -p /opt/pgt/whl /opt/pgt/data

WORKDIR /opt/pgt/data
EXPOSE 9099
ENTRYPOINT ["/opt/pgt/entrypoint.sh"]