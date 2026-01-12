import asyncio, paramiko, logging, socket, os
from collections import defaultdict

# Port Check Approach:
def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # return s.connect_ex(('localhost', port)) == 0
        return s.connect_ex(('0.0.0.0', port)) == 0

if is_port_in_use(8765):
    print("Another instance of the server is already running.")
    exit(1)

# Define the log file path
logfile = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'logs', 'websocket_server.log'))

# logging.getLogger("paramiko").setLevel(logging.info)
logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Ensure the logs directory exists
os.makedirs(os.path.dirname(logfile), exist_ok=True)

# Create a logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create a file handler for logging to a file
file_handler = logging.FileHandler(logfile)
file_handler.setLevel(logging.ERROR)

# Create a console handler for logging to the console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.ERROR)

# Define a logging format
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add the handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)

async def handle_ssh_shell(ssh_shell, websocket):
    """
    Forward data from the SSH shell to the WebSocket client in real-time.
    """
    try:
        while True:
            # Check if data is available from the SSH shell
            if ssh_shell.recv_ready():
                data = ssh_shell.recv(2048).decode("utf-8", errors="ignore")
                await websocket.send(data)  # Send data to the client

            # Check if data is available from the WebSocket client
            try:
                command = await asyncio.wait_for(websocket.recv(), timeout=0.1)
                ssh_shell.send(command)  # Send command to the SSH shell
            except asyncio.TimeoutError:
                pass

            await asyncio.sleep(0.1)  # Avoid busy-waiting
    except Exception as e:
        logger.error(f"SSH shell error: {e}")
    finally:
        ssh_shell.close()

async def handle_connection(websocket, path):
    # logger.info(f"New WebSocket connection from {websocket.remote_address}")
    try:
        # Receive connection details from the client
        connection_details = await websocket.recv()
        ssh_host, ssh_port, ssh_username, ssh_password = connection_details.split("|")
        ssh_port = int(ssh_port)  # Convert port to integer

        # Establish SSH connection to the remote device
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ssh_host, port=ssh_port, username=ssh_username, password=ssh_password)
        logger.info(f"{websocket.remote_address} {ssh_username} Connected to {ssh_host}:{ssh_port} via SSH")

        # Open an interactive shell
        ssh_shell = ssh.invoke_shell()
        await websocket.send("SSH connection established. Starting real-time CLI...")

        # Wait for the device to be ready (e.g., after login banner)
        output = ""
        while True:
            if ssh_shell.recv_ready():
                data = ssh_shell.recv(1024).decode("utf-8", errors="ignore")
                output += data
                await websocket.send(data)  # Send data to the client
                if ">" in output or "#" in output or "$" in output:  # Device prompt detected
                    break
            await asyncio.sleep(0.1)

        # Disable paging (for devices like Cisco switches/routers)
        if "cisco" in output.lower():  # Check if the device is a Cisco device
            ssh_shell.send("terminal length 0\n")
            await asyncio.sleep(1)  # Wait for the command to execute

        # Track the connection
        #connections[websocket] = {"ssh": ssh, "ssh_shell": ssh_shell}            

        # Start forwarding data from the SSH shell to the WebSocket client
        await handle_ssh_shell(ssh_shell, websocket)

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await websocket.send(f"Error: {e}")
    finally:
        # Close the SSH connection
        if "ssh" in locals():
            ssh.close()
            logger.info("SSH connection closed")
        logger.info("Client disconnected")
        #connections.pop(websocket, None)


def start_websocket_server_in_background():
    import asyncio, websockets

    async def run_server():
        server = await websockets.serve(handle_connection, "0.0.0.0", 8765)
        await server.wait_closed()

    loop = asyncio.get_event_loop()
    loop.create_task(run_server())