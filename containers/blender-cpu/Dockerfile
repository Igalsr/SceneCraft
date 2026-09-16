ARG BLENDER_PLATFORM=linux/amd64
FROM --platform=${BLENDER_PLATFORM} debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171

ARG BLENDER_ARCHIVE_URL=https://download.blender.org/release/Blender5.2/blender-5.2.2-linux-x64.tar.xz
ARG BLENDER_ARCHIVE_SHA256=84098912789dc450e95697c4184fb8a90acbe5111c2ba4aede3fecb57806a168

RUN test -n "$BLENDER_ARCHIVE_URL" && test -n "$BLENDER_ARCHIVE_SHA256"
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl xz-utils libegl1 libgl1 libsm6 libxext6 libxi6 libxrender1 libxfixes3 libxkbcommon0 \
    && rm -rf /var/lib/apt/lists/*
RUN curl --fail --location "$BLENDER_ARCHIVE_URL" --output /tmp/blender.tar.xz \
    && echo "$BLENDER_ARCHIVE_SHA256  /tmp/blender.tar.xz" | sha256sum --check - \
    && mkdir -p /opt/blender \
    && tar -xJf /tmp/blender.tar.xz --strip-components=1 -C /opt/blender \
    && rm /tmp/blender.tar.xz

ENV PATH="/opt/blender:${PATH}"
WORKDIR /workspace
ENTRYPOINT ["blender", "--background", "--factory-startup"]
