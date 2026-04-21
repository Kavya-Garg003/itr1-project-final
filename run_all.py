import subprocess
import time
import os
import signal
import sys
from pathlib import Path

# Load .env variables
def load_env():
    env_path = Path('.env')
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ[key.strip()] = val.strip()

def main():
    load_env()
    
    root = Path(__file__).parent.resolve()
    python_exe = str(root / ".venv311" / "Scripts" / "python.exe")
    uvicorn_exe = str(root / ".venv311" / "Scripts" / "uvicorn.exe")
    npx_exe = "npx.cmd" if os.name == "nt" else "npx"
    node_exe = "node.exe" if os.name == "nt" else "node"
    
    os.environ['UPLOAD_DIR'] = str(root / "uploads")
    os.makedirs(os.environ['UPLOAD_DIR'], exist_ok=True)
    
    services = [
        {
            "name": "DocParser",
            "cmd": [uvicorn_exe, "main:app", "--host", "0.0.0.0", "--port", "8002", "--reload"],
            "cwd": str(root / "doc-parser"),
            "env": {"PYTHONPATH": str(root)}
        },
        {
            "name": "RAGService",
            "cmd": [uvicorn_exe, "main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"],
            "cwd": str(root / "rag-service"),
            "env": {"PYTHONPATH": str(root), "VECTOR_STORE_DIR": str(root / "knowledge-base" / "vector_store"), "DEFAULT_AY": "AY2024-25"}
        },
        {
            "name": "AgentOrch",
            "cmd": [uvicorn_exe, "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"],
            "cwd": str(root / "agent-orchestrator"),
            "env": {"PYTHONPATH": str(root), "RAG_SERVICE_URL": "http://localhost:8001", "DOC_PARSER_URL": "http://localhost:8002"}
        },
        {
            "name": "APIGateway",
            "cmd": [node_exe, "src/index.js"],
            "cwd": str(root / "api-gateway"),
            "env": {"PORT": "3001", "DOC_PARSER_URL": "http://localhost:8002", "RAG_SERVICE_URL": "http://localhost:8001", "AGENT_ORCH_URL": "http://localhost:8000", "FRONTEND_URL": "http://localhost:3000", "SKIP_AUTH": "true", "JWT_SECRET": "dev-secret"}
        },
        {
            "name": "Frontend",
            "cmd": [npx_exe, "next", "dev", "--port", "3000"],
            "cwd": str(root / "frontend"),
            "env": {"NEXT_PUBLIC_API_URL": "http://localhost:3001"}
        }
    ]

    procs = []
    
    print("Starting all ITR-1 services natively in Python...")
    
    # Open log file
    log_file = open("server_logs.txt", "w")

    for svc in services:
        print(f"Starting {svc['name']}...")
        
        env = os.environ.copy()
        env.update(svc.get("env", {}))
        
        p = subprocess.Popen(
            svc["cmd"], 
            cwd=svc["cwd"], 
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )
        procs.append((svc["name"], p))
        time.sleep(2)  # stagger startup

    print("\n========================================")
    print("  All 5 services launched successfully!")
    print("========================================")
    print("  Frontend:           http://localhost:3000")
    print("  API Gateway:        http://localhost:3001")
    print("  Agent Orchestrator: http://localhost:8000")
    print("  RAG Service:        http://localhost:8001")
    print("  Doc Parser:         http://localhost:8002")
    print("\nLogs are being saved to server_logs.txt")
    print("Running in background... Leave this terminal open to keep servers running.")
    print("Press Ctrl+C to terminate all services gracefully.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping all services...")
        for name, p in procs:
            p.terminate()

if __name__ == "__main__":
    main()
