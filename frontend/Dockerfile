FROM node:24-alpine AS base

# Dependencias para better-sqlite3 y compilacion nativa si es requerida
RUN apk add --no-cache libc6-compat python3 make g++

WORKDIR /app

# Instalar dependencias
COPY package.json package-lock.json* ./
RUN npm ci

# Copiar codigo fuente
COPY . .

# Variables de compilacion
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

RUN npm run build

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["npm", "start"]
