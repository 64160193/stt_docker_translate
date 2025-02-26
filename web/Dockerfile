FROM node:18-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy source code
COPY . .

# Start development server
CMD ["npm", "run", "dev"]

# Expose port 3000
EXPOSE 3000