#!/bin/bash
# Certificate generation script for gRPC Latency Tests
set -e

echo "🔐 Generating TLS certificates for gRPC Latency Tests..."

# Create certificate directories
echo "📁 Creating certificate directories..."
mkdir -p df/certs smft/certs

cd df/certs

# Generate CA private key
echo "🔑 Generating CA private key..."
openssl genrsa -out ca.key 4096

# Generate CA certificate
echo "📜 Generating CA certificate..."
openssl req -new -x509 -key ca.key -sha256 \
    -subj "/C=RU/ST=Moscow/O=TestLab/CN=TestCA" \
    -days 365 -out ca.crt

# Generate server private key
echo "🔑 Generating server private key..."
openssl genrsa -out server.key 4096

# Generate server certificate signing request
echo "📝 Generating server certificate signing request..."
openssl req -new -key server.key \
    -subj "/C=RU/ST=Moscow/O=TestLab/CN=localhost" \
    -out server.csr

# Sign server certificate with CA
echo "✍️  Signing server certificate..."
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
    -CAcreateserial -out server.crt -days 365 -sha256

# Generate client private key
echo "🔑 Generating client private key..."
openssl genrsa -out client.key 4096

# Generate client certificate signing request
echo "📝 Generating client certificate signing request..."
openssl req -new -key client.key \
    -subj "/C=RU/ST=Moscow/O=TestLab/CN=smft-client" \
    -out client.csr

# Sign client certificate with CA
echo "✍️  Signing client certificate..."
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key \
    -CAcreateserial -out client.crt -days 365 -sha256

# Copy certificates to SMFT directory
echo "📋 Copying certificates to SMFT directory..."
cp ca.crt client.crt client.key ../../smft/certs/

# Set appropriate permissions
echo "🔒 Setting certificate permissions..."
chmod 600 *.key ../../smft/certs/*.key
chmod 644 *.crt *.csr ../../smft/certs/*.crt

# Clean up CSR files
echo "🧹 Cleaning up temporary files..."
rm -f server.csr client.csr

cd ../..

echo ""
echo "✅ Certificate generation complete!"
echo ""
echo "Generated certificates:"
echo "  📁 df/certs/:"
echo "    - ca.crt (CA certificate)"
echo "    - ca.key (CA private key)"  
echo "    - server.crt (Server certificate)"
echo "    - server.key (Server private key)"
echo ""
echo "  📁 smft/certs/:"
echo "    - ca.crt (CA certificate)"
echo "    - client.crt (Client certificate)"
echo "    - client.key (Client private key)"
echo ""
echo "🔍 Verify certificates:"
echo "  openssl x509 -in df/certs/server.crt -text -noout | head -20"
echo "  openssl verify -CAfile df/certs/ca.crt df/certs/server.crt"
echo "  openssl verify -CAfile smft/certs/ca.crt smft/certs/client.crt"
echo ""
echo "⚠️  Note: These are self-signed certificates for testing only!"
echo "   Do not use in production environments."