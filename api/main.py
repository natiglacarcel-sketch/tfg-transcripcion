from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import subprocess
import threading
import time
import uuid

app = FastAPI(
    title="Servidor de Transcripción TFG",
    version="2.1.0",
    description="API REST para transcripción automática de audio con Whisper y Docker"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path("/srv/files")
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"
WEB_DIR = Path("/app/web")

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB

# Trabajos en memoria
JOBS = {}
JOBS_LOCK = threading.Lock()


def ejecutar_comando(comando, cwd=None):
    return subprocess.run(
        comando,
        cwd=cwd,
        capture_output=True,
        text=True
    )


def asegurar_directorios():
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DIR.mkdir(parents=True, exist_ok=True)


def extension_permitida(nombre_archivo: str) -> bool:
    return Path(nombre_archivo).suffix.lower() in ALLOWED_EXTENSIONS


def sincronizar_git():
    # No tratamos commit sin cambios como error fatal
    ejecutar_comando(["git", "add", "data/input", "data/output"], cwd=BASE_DIR)
    ejecutar_comando(
        ["git", "commit", "-m", "Añadidos audio y transcripción automática desde API"],
        cwd=BASE_DIR
    )
    ejecutar_comando(["git", "push"], cwd=BASE_DIR)


def esperar_salida(nombre_base: str, timeout: int = 90, pausa: float = 2.0):
    """
    Espera a que aparezca el TXT en data/output.
    Devuelve un dict con:
      - encontrado: bool
      - archivos: lista de archivos detectados
    """
    inicio = time.time()

    while time.time() - inicio < timeout:
        archivos = [
            f.name for f in OUTPUT_DIR.glob(f"{nombre_base}.*")
            if f.is_file()
        ]

        if f"{nombre_base}.txt" in archivos:
            return {
                "encontrado": True,
                "archivos": archivos
            }

        time.sleep(pausa)

    archivos_finales = [
        f.name for f in OUTPUT_DIR.glob(f"{nombre_base}.*")
        if f.is_file()
    ]

    return {
        "encontrado": f"{nombre_base}.txt" in archivos_finales,
        "archivos": archivos_finales
    }


def actualizar_job(job_id: str, **campos):
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(campos)


def procesar_transcripcion(job_id: str, filename: str):
    try:
        actualizar_job(job_id, estado="procesando", inicio=time.time())

        comando = [
            "docker", "run", "--rm",
            "-v", f"{BASE_DIR}:/srv/files:Z",
            "whisper-local",
            f"/srv/files/data/input/{filename}",
            "--output_dir", "/srv/files/data/output",
            "--language", "es",
            "--model", "small",
            "--compute_type", "int8",
            "--output_format", "all"
        ]

        resultado = ejecutar_comando(comando)

        if resultado.returncode != 0:
            actualizar_job(
                job_id,
                estado="error",
                error={
                    "mensaje": "Error ejecutando Whisper",
                    "stderr": resultado.stderr.strip(),
                    "stdout": resultado.stdout.strip()
                },
                fin=time.time()
            )
            return

        nombre_base = Path(filename).stem

        # pequeña pausa inicial
        time.sleep(2)

        resultado_espera = esperar_salida(nombre_base, timeout=90, pausa=2.0)
        archivos_detectados = resultado_espera["archivos"]

        if not resultado_espera["encontrado"]:
            actualizar_job(
                job_id,
                estado="error",
                error={
                    "mensaje": "La transcripción terminó pero el TXT no apareció tras la espera ampliada",
                    "esperado": f"{nombre_base}.txt",
                    "archivos_en_output": archivos_detectados
                },
                fin=time.time()
            )
            return

        sincronizar_git()

        fin = time.time()
        actualizar_job(
            job_id,
            estado="completado",
            fin=fin,
            duracion_segundos=round(fin - JOBS[job_id]["inicio"], 2),
            archivo_base=nombre_base,
            archivos_generados={
                "txt": f"{nombre_base}.txt",
                "srt": f"{nombre_base}.srt",
                "vtt": f"{nombre_base}.vtt",
                "tsv": f"{nombre_base}.tsv",
                "json": f"{nombre_base}.json"
            },
            urls={
                "txt": f"/transcripcion/{nombre_base}.txt",
                "descarga_txt": f"/descargar/{nombre_base}.txt",
                "descarga_srt": f"/descargar/{nombre_base}.srt"
            }
        )

    except Exception as e:
        actualizar_job(
            job_id,
            estado="error",
            error={"mensaje": str(e)},
            fin=time.time()
        )


@app.on_event("startup")
def startup_event():
    asegurar_directorios()


@app.get("/")
def servir_index():
    index_path = WEB_DIR / "index.html"

    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html no encontrado")

    return FileResponse(index_path)


@app.get("/ping")
def ping():
    return {"ok": True, "mensaje": "API funcionando"}


@app.get("/files")
def listar_archivos():
    input_files = [f.name for f in INPUT_DIR.glob("*") if f.is_file()]
    output_files = [f.name for f in OUTPUT_DIR.glob("*") if f.is_file()]

    return {
        "input_files": sorted(input_files),
        "output_files": sorted(output_files)
    }


@app.get("/trabajos")
def listar_trabajos():
    with JOBS_LOCK:
        return JOBS


@app.get("/estado/{job_id}")
def estado_trabajo(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")

    return job


@app.get("/resultado/{job_id}")
def resultado_trabajo(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")

    if job["estado"] == "error":
        raise HTTPException(status_code=500, detail=job.get("error", "Error en el trabajo"))

    if job["estado"] != "completado":
        return {
            "ok": False,
            "estado": job["estado"],
            "mensaje": "La transcripción todavía no está lista"
        }

    return {
        "ok": True,
        "estado": job["estado"],
        "archivo_entrada": job["archivo_entrada"],
        "archivo_base": job["archivo_base"],
        "duracion_segundos": job.get("duracion_segundos"),
        "archivos_generados": job["archivos_generados"],
        "urls": job["urls"]
    }


@app.get("/transcripcion/{nombre}", response_class=PlainTextResponse)
def ver_transcripcion(nombre: str):
    ruta = OUTPUT_DIR / nombre

    if not ruta.exists():
        raise HTTPException(status_code=404, detail="Transcripción no encontrada")

    return ruta.read_text(encoding="utf-8")


@app.get("/descargar/{nombre}")
def descargar_archivo(nombre: str):
    ruta = OUTPUT_DIR / nombre

    if not ruta.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    return FileResponse(
        path=ruta,
        filename=ruta.name,
        media_type="application/octet-stream"
    )


@app.post("/transcribir")
def transcribir(file: UploadFile = File(...)):
    asegurar_directorios()

    if not file.filename:
        raise HTTPException(status_code=400, detail="Archivo inválido")

    if not extension_permitida(file.filename):
        raise HTTPException(status_code=400, detail="Formato de audio no permitido")

    destino = INPUT_DIR / file.filename

    total_bytes = 0
    with destino.open("wb") as buffer:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break

            total_bytes += len(chunk)

            if total_bytes > MAX_FILE_SIZE_BYTES:
                destino.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Archivo demasiado grande")

            buffer.write(chunk)

    job_id = str(uuid.uuid4())

    with JOBS_LOCK:
        JOBS[job_id] = {
            "job_id": job_id,
            "estado": "pendiente",
            "archivo_entrada": file.filename,
            "tamano_bytes": total_bytes,
            "inicio": None,
            "fin": None
        }

    hilo = threading.Thread(
        target=procesar_transcripcion,
        args=(job_id, file.filename),
        daemon=True
    )
    hilo.start()

    return {
        "ok": True,
        "mensaje": "Trabajo de transcripción creado",
        "job_id": job_id,
        "estado": "pendiente",
        "archivo_entrada": file.filename,
        "url_estado": f"/estado/{job_id}",
        "url_resultado": f"/resultado/{job_id}"
    }


app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")
