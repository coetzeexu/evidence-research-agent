FROM node:22-bookworm-slim AS web
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY apps ./apps
COPY packages ./packages
COPY index.html tsconfig.json vite.config.ts vite.report.config.ts ./
RUN npm run build

FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=web /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY backend ./backend
RUN uv sync --frozen --no-dev
COPY --from=web /app/node_modules ./node_modules
COPY --from=web /app/dist ./dist
COPY prompts ./prompts
COPY skills ./skills
COPY resources ./resources
COPY samples ./samples
COPY packages ./packages
COPY tools ./tools
ENV RESEARCH_HOST=0.0.0.0 RESEARCH_DATA_DIR=/data
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "research", "serve"]
