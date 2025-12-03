import socket
import threading
import base64
import hashlib
import struct
import json
import time

# --- CONFIGURAÇÕES ---
HOST = '127.0.0.1'
PORT = 8080
MAGIC_STRING = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11" # Constante do protocolo WebSocket
XOR_KEY = "SEGREDOSUPERSECRETO" # Chave para criptografia simétrica

clients = [] # Lista de clientes conectados (Chat)
dashboards = [] # Lista de admins conectados (Monitoramento)

def xor_cipher(text, key):
    """Criptografia XOR simples para visualização no Wireshark"""
    encrypted = []
    for i, char in enumerate(text):
        key_char = key[i % len(key)]
        encrypted.append(chr(ord(char) ^ ord(key_char)))
    return "".join(encrypted)

def create_handshake_response(headers):
    """Gera a resposta HTTP 101 para upgrade de protocolo"""
    key = headers['Sec-WebSocket-Key']
    accept_key = base64.b64encode(hashlib.sha1((key + MAGIC_STRING).encode()).digest()).decode()
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key}\r\n\r\n"
    ).encode()

def parse_frame(data):
    """Decodifica o frame binário do WebSocket (RFC 6455)"""
    if len(data) < 2: return None
    
    # Byte 1: Máscara e Tamanho
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
    """Cria um frame WebSocket para enviar ao navegador (sem máscara)"""
    msg_bytes = message.encode('utf-8')
    length = len(msg_bytes)
    
    # Byte 0: Fin=1, Opcode=1 (Texto) -> 10000001 -> 129
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
    """Envia mensagem para todos os clientes conectados"""
    # Se for mensagem de sistema, não precisa cifrar com XOR do chat, apenas envia JSON puro
    msg_to_send = message
    
    print(f"[LOG] Enviando broadcast: {msg_to_send[:50]}...")
    frame = create_frame(msg_to_send)
    
    # Enviar para Dashboards (texto puro)
    for dash in dashboards:
        try:
            dash.send(frame)
        except:
            dashboards.remove(dash)

    # Enviar para Clientes (Chat)
    # Se não for mensagem de sistema, clientes esperam receber cifrado!
    if not is_system_msg:
         # O payload JSON deve estar cifrado
         pass 

    for client in clients:
        try:
            client.send(frame)
        except:
            clients.remove(client)

def handle_client(conn, addr):
    """Função executada por cada THREAD"""
    print(f"[NOVA CONEXÃO] {addr} conectado.")
    
    # 1. Handshake
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
    
    # Identificar se é Dashboard ou Chat
    # (Simplificação: Dashboard envia um JSON específico logo após conectar)
    client_type = "chat" 
    
    try:
        while True:
            data = conn.recv(2048)
            if not data: break
            
            # Decodificar o frame do WebSocket
            text_received = parse_frame(data)
            
            if not text_received: continue

            # Lógica para registrar tipos de clientes
            try:
                msg_json = json.loads(text_received)
                if msg_json.get('type') == 'register_dash':
                    dashboards.append(conn)
                    client_type = "dash"
                    print(f"Dashboard registrado: {addr}")
                    continue
                
                if msg_json.get('type') == 'register_chat':
                    if conn not in clients: clients.append(conn)
                    msg_json['text'] = f"Entrou na sala." # Mensagem de sistema
                    broadcast(json.dumps(msg_json))
                    continue

                # MENSAGEM DE CHAT (CRIPTOGRAFADA)
                if msg_json.get('type') == 'message':
                    encrypted_text = msg_json.get('payload')
                    
                    # 1. Descriptografar no servidor (simulando processamento seguro)
                    decrypted_text = xor_cipher(encrypted_text, XOR_KEY)
                    
                    print(f"\n--- CRIPTOGRAFIA ---")
                    print(f"Recebido (Cifrado): {encrypted_text}")
                    print(f"Decifrado (Servidor): {decrypted_text}")
                    print(f"--------------------\n")
                    
                    # Enviar para o Dashboard ver o log
                    log_msg = json.dumps({
                        "type": "log", 
                        "encrypted": encrypted_text, 
                        "decrypted": decrypted_text,
                        "user": msg_json.get('user')
                    })
                    for dash in dashboards: dash.send(create_frame(log_msg))

                    # 2. Reenviar para todos (Broadcast)
                    # No mundo real, re-criptografaríamos com a chave de cada cliente.
                    # Aqui, reenviamos o payload original para validar o conceito.
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

# --- INICIALIZAÇÃO ---
def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()
    print(f"[SERVIDOR INICIADO] Ouvindo em {HOST}:{PORT}")
    print("[INFO] Interface Gráfica disponível nos arquivos .html")

    while True:
        conn, addr = server.accept()
        # CRIAÇÃO DA THREAD (Requisito fundamental)
        thread = threading.Thread(target=handle_client, args=(conn, addr))
        thread.start()
        print(f"[THREADS ATIVAS] {threading.active_count() - 1}")

if __name__ == "__main__":
    start_server()