FROM node:22-alpine AS build
ARG VITE_API_BASE=https://api.example.com/v1
ENV VITE_API_BASE=$VITE_API_BASE
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html/admin
COPY deploy/nginx/default.conf /etc/nginx/conf.d/default.conf

