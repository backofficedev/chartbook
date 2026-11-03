# VHS, with Python, ChartBook and the tools the tapes show. Built by record.py, which hands it a
# wheel of this checkout's ChartBook in the build context.
FROM ghcr.io/charmbracelet/vhs

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv git unzip jq \
 && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/chartbook
ENV PATH=/opt/chartbook/bin:$PATH
COPY chartbook-*.whl /tmp/
RUN pip install --no-cache-dir /tmp/chartbook-*.whl && rm /tmp/chartbook-*.whl

# Plotting's static images are drawn by a headless Chrome; VHS ships Chromium
ENV BROWSER_PATH=/usr/bin/chromium
RUN git config --global user.name "ChartBook" && git config --global user.email "docs@example.com" \
 && git config --global init.defaultBranch main
WORKDIR /work
