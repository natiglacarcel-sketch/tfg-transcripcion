from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import subprocess
import threading
import time
import uuid

app = FastAPI(title="Servidor de Transcripción TFG", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

APP_DIR = Path("/app")
INPUT_DIR = APP_DIR / "data" / "input"
OUTPUT_DIR = APP_DIR / "data" / "output"
WEB_DIR = APP_DIR / "web"

HOST_PROJECT_DIR = "/home/nati/tfg-transcripcion"

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}
MODELOS_VALIDOS = {"tiny", "base", "small"}

JOBS = {}
LOCK = threading.Lock()


def ejecutar(comando):
    return subprocess.run(comando, capture_output=True, text=True)


def esperar_txt(nombre_base, timeout=90):
    inicio = time.time()
    while time.time() - inicio < timeout:
        if (OUTPUT_DIR / f"{nombre_base}.txt").exists():
            return True
        time.sleep(2)
    return False


def procesar(job_id, filename, model):
    try:
        with LOCK:
            JOBS[job_id]["estado"] = "procesando"
            JOBS[job_id]["inicio"] = time.time()

        comando = [
            "docker", "run", "--rm",
            "-v", f"{HOST_PROJECT_DIR}:/srv/files:Z",
            "whisper-local",
            f"/srv/files/data/input/{filename}",
            "--output_dir", "/srv/files/data/output",
            "--language", "es",
            "--model", model,
            "--compute_type", "int8",
            "--output_format", "all"
        ]

        resultado = ejecutar(comando)

        if resultado.returncode != 0:
            raise Exception(resultado.stderr)

        nombre_base = Path(filename).stem

        if not esperar_txt(nombre_base):
            raise Exception("TXT no generado")

        fin = time.time()

        with LOCK:
            JOBS[job_id].update({
                "estado": "completado",
                "fin": fin,
                "duracion": round(fin - JOBS[job_id]["inicio"], 2),
                "modelo": model,
                "archivo_base": nombre_base,
                "urls": {
                    "txt": f"/transcripcion/{nombre_base}.txt",
                    "descarga_txt": f"/descargar/{nombre_base}.txt",
                    "descarga_srt": f"/descargar/{nombre_base}.srt",
                    "descarga_vtt": f"/descargar/{nombre_base}.vtt",
                    "descarga_tsv": f"/descargar/{nombre_base}.tsv",
                    "descarga_json": f"/descargar/{nombre_base}.json"                    
                }
            })

    except Exception as e:
        with LOCK:
            JOBS[job_id]["estado"] = "error"
            JOBS[job_id]["error"] = str(e)


@app.get("/ping")
def ping():
    return {"ok": True}


@app.get("/")
def home():
    return FileResponse(WEB_DIR / "index.html")


@app.post("/transcribir")
def transcribir(
    file: UploadFile = File(...),
    model: str = Form("small")
):
    if model not in MODELOS_VALIDOS:
        raise HTTPException(400, "Modelo inválido")

    destino = INPUT_DIR / file.filename
    with destino.open("wb") as f:
        f.write(file.file.read())

    job_id = str(uuid.uuid4())

    with LOCK:
        JOBS[job_id] = {
            "estado": "pendiente",
            "archivo": file.filename
        }

    threading.Thread(
        target=procesar,
        args=(job_id, file.filename, model),
        daemon=True
    ).start()

    return {
        "job_id": job_id,
        "estado": "pendiente"
    }


@app.get("/estado/{job_id}")
def estado(job_id: str):
    return JOBS.get(job_id, {"error": "no existe"})


@app.get("/resultado/{job_id}")
def resultado(job_id: str):
    job = JOBS.get(job_id)

    if not job:
        raise HTTPException(404)

    if job["estado"] != "completado":
        return {"estado": job["estado"]}

    return job


@app.get("/transcripcion/{nombre}", response_class=PlainTextResponse)
def ver(nombre: str):
    return (OUTPUT_DIR / nombre).read_text()


@app.get("/descargar/{nombre}")
def descargar(nombre: str):
    return FileResponse(OUTPUT_DIR / nombre)


app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")
