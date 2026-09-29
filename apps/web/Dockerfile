FROM node:22-alpine AS deps
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm install --omit=dev=false

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web ./
# Empty or loopback means the browser uses same-origin /api (see src/lib/api.ts).
ARG NEXT_PUBLIC_API_URL=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
ENV PORT=4000
# Prefer IPv4. Node on Alpine otherwise tries unreachable IPv6 answers from Docker DNS.
ENV NODE_OPTIONS=--dns-result-order=ipv4first
# Docker network hostname of the API service. Override for a non-compose layout.
ENV API_INTERNAL_URL=http://api:8008
RUN echo "hosts: files dns" > /etc/nsswitch.conf
EXPOSE 4000
CMD ["node", "server.js"]
