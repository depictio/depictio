# Dev-only image: runs the Vite dev server with HMR.
# Used by the opt-in `react-frontend` service in docker-compose.dev.yaml.
FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY . .

EXPOSE 5173
ENV HOST=0.0.0.0
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
