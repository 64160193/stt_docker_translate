FROM node:18-alpine
WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install
RUN npm install -g vite

# Copy source code
COPY . .

# Start development server using npx
CMD ["npx", "vite"]

# Expose port 3000
EXPOSE 3000