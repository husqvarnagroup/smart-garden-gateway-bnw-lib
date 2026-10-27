# Create root CA
```
openssl genrsa 2048 > ca-key.pem
openssl req -new -x509 -nodes -days 36500 -key ca-key.pem -out ca-cert.pem -subj "/C=CH/ST=ZH/L=Zurich/O=GARDENA GmbH/OU=digital hub Zurich/CN=cloud-ca"
```

# Create a server certificate
```
openssl req -newkey rsa:2048 -nodes \
   -keyout server-key.pem \
   -out server-req.pem \
   -subj "/C=CH/ST=ZH/L=Zurich/O=GARDENA GmbH/OU=digital hub Zurich/CN=127.0.0.1"
   
openssl x509 -req -days 36500 -sha256 \
   -in server-req.pem \
   -out server-cert.pem \
   -CA ca-cert.pem \
   -CAkey ca-key.pem
```

# Create a client certificate
```
openssl req -newkey rsa:2048 -nodes \
   -keyout client-key.pem \
   -out client-req.pem \
   -subj "/C=CH/ST=ZH/L=Zurich/O=GARDENA GmbH/OU=digital hub Zurich/CN=client"
   
openssl x509 -req -days 36500 -sha256 -set_serial 02 \
   -in client-req.pem \
   -out client-cert.pem \
   -CA ca-cert.pem \
   -CAkey ca-key.pem
```
