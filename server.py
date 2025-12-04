import socket
import threading
import base64
import hashlib
import struct
import json
import time

HOST = '127.0.0.1'
PORT = 8080
MAGIC_STRING = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11" 
XOR_KEY = "SEGREDOSUPERSECRETO" 

clients = [] 
dashboards = [] 

def xor_cipher(text, key):
    encrypted = []
    for i, char in enumerate(text):
        key_char = key[i % len(key)]
        encrypted.append(chr(ord(char) ^ ord(key_char)))
    return "".join(encrypted)

def create_handshake_response(headers):
    key = headers['Sec-WebSocket-Key']
    accept_key = base64.b64encode(hashlib.sha1((key + MAGIC_STRING).encode()).digest()).decode()
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key}\r\n\r\n"
    ).encode()

def parse_frame(data):
    if len(data) < 2: return None
    
    second_byte = data[1]
    is_masked = second_byte & 128
    payload_len = second_byte & 127
    
    start_payload = 2
    if payload_len == 126:
        start_payload = 4
    elif payload_len == 127:
        start_payload = 10
    
    masks = data[start_payload : start_payload + 4]
    start_payload += 4
    encrypted_payload = data[start_payload:]
    
    decoded = bytearray()
    for i, byte in enumerate(encrypted_payload):
        decoded.append(byte ^ masks[i % 4])
    
    return decoded.decode('utf-8')

def create_frame(message):
    msg_bytes = message.encode('utf-8')
    length = len(msg_bytes)
    
    frame = bytearray([129])
    
    if length <= 125:
        frame.append(length)
    elif length <= 65535:
        frame.append(126)
        frame.extend(struct.pack("!H", length))
    else:
        frame.append(127)
        frame.extend(struct.pack("!Q", length))
        
    frame.extend(msg_bytes)
    return frame

def broadcast(message, is_system_msg=False):
    msg_to_send = message
    
    frame = create_frame(msg_to_send)
    
    for dash in dashboards:
        try:
            dash.send(frame)
        except:
            dashboards.remove(dash)

    if not is_system_msg:
         pass 

    for client in clients:
        try:
            client.send(frame)
        except:
            clients.remove(client)

def handle_client(conn, addr):
    print(f"[NOVA CONEXÃO] {addr} conectado.")
    
    data = conn.recv(1024).decode()
    headers = {}
    for line in data.split("\r\n")[1:]:
        if ": " in line:
            key, value = line.split(": ", 1)
            headers[key] = value
            
    if 'Sec-WebSocket-Key' not in headers:
        print("Não é um request WebSocket.")
        conn.close()
        return
    conn.send(create_handshake_response(headers))
    try:
        while True:
            data = conn.recv(2048)
            if not data: break
            
            text_received = parse_frame(data)
            
            if not text_received: continue

            try:
                msg_json = json.loads(text_received)
                if msg_json.get('type') == 'register_dash':
                    dashboards.append(conn)
                    print(f"Dashboard registrado: {addr}")
                    continue
                
                if msg_json.get('type') == 'register_chat':
                    if conn not in clients: clients.append(conn)
                    msg_json['text'] = f"Entrou na sala."
                    broadcast(json.dumps(msg_json))
                    continue

                if msg_json.get('type') == 'message':
                    encrypted_text = msg_json.get('payload')
                    
                    decrypted_text = xor_cipher(encrypted_text, XOR_KEY)
                    
                    log_msg = json.dumps({
                        "type": "log", 
                        "encrypted": encrypted_text, 
                        "decrypted": decrypted_text,
                        "user": msg_json.get('user')
                    })
                    for dash in dashboards: dash.send(create_frame(log_msg))

                    broadcast(json.dumps(msg_json))

            except json.JSONDecodeError:
                pass
                
    except Exception as e:
        print(f"Erro: {e}")
    finally:
        if conn in clients: clients.remove(conn)
        if conn in dashboards: dashboards.remove(conn)
        conn.close()
        print(f"[DESCONECTADO] {addr}")

def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()
    print(f"[SERVIDOR INICIADO] Ouvindo em {HOST}:{PORT}")
    print("[INFO] Interface Gráfica disponível nos arquivos .html")

    while True:
        conn, addr = server.accept()
        thread = threading.Thread(target=handle_client, args=(conn, addr))
        thread.start()
        print(f"[THREADS ATIVAS] {threading.active_count() - 1}")

if __name__ == "__main__":
    start_server()