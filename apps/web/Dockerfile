FROM node:24.21.0-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20
WORKDIR /workspace
RUN npm install --global pnpm@12.9.1
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile
COPY packages/contracts/generated packages/contracts/generated
COPY apps/web/index.html apps/web/tsconfig.json apps/web/vite.config.ts apps/web/
COPY apps/web/src apps/web/src
COPY apps/web/tests apps/web/tests
COPY apps/web/playwright.config.ts apps/web/playwright.config.ts
RUN pnpm build
USER node
EXPOSE 4173
WORKDIR /workspace/apps/web
CMD ["node", "node_modules/vite/bin/vite.js", "preview", "--configLoader", "runner", "--host", "0.0.0.0", "--port", "4173", "--strictPort"]
