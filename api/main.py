from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import subprocess
import time
from typing import Dict

app = FastAPI(
    title="Servidor de Transcripción TFG",
    version="1.1.0",
    description="API REST para transcripción automática de audio con Whisper y Docker"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path("/app")
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"
WEB_DIR = BASE_DIR / "web"

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024


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


def esperar_archivo(ruta: Path, intentos: int = 10, espera: float = 1.0):
    """
    Espera a que aparezca un archivo en disco.
    Evita errores cuando Whisper tarda un momento en escribir los resultados.
    """
    for _ in range(intentos):
        if ruta.exists():
            return True
        time.sleep(espera)
    return False


def sincronizar_git() -> Dict:
    resultados = {}

    add_result = ejecutar_comando(
        ["git", "add", "data/input", "data/output"],
        cwd=BASE_DIR
    )

    commit_result = ejecutar_comando(
        ["git", "commit", "-m", "Añadidos audio y transcripción automática desde API"],
        cwd=BASE_DIR
    )

    push_result = ejecutar_comando(
        ["git", "push"],
        cwd=BASE_DIR
    )

    resultados["git_add"] = add_result.returncode
    resultados["git_commit"] = commit_result.returncode
    resultados["git_push"] = push_result.returncode

    return resultados


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
    return {
        "ok": True,
        "mensaje": "API funcionando"
    }


@app.get("/files")
def listar_archivos():

    input_files = [f.name for f in INPUT_DIR.glob("*") if f.is_file()]
    output_files = [f.name for f in OUTPUT_DIR.glob("*") if f.is_file()]

    return {
        "input_files": sorted(input_files),
        "output_files": sorted(output_files)
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
        raise HTTPException(
            status_code=400,
            detail="Formato de audio no permitido"
        )

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
                raise HTTPException(
                    status_code=413,
                    detail="Archivo demasiado grande"
                )

            buffer.write(chunk)

    comando = [
        "docker", "run", "--rm",
        "-v", f"{BASE_DIR}:/srv/files:Z",
        "whisper-local",
        f"/srv/files/data/input/{file.filename}",
        "--output_dir", "/srv/files/data/output",
        "--language", "es",
        "--model", "small",
        "--compute_type", "int8",
        "--output_format", "all"
    ]

    resultado = ejecutar_comando(comando)

    if resultado.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "mensaje": "Error ejecutando Whisper",
                "stderr": resultado.stderr
            }
        )

    nombre_base = Path(file.filename).stem

    archivos = {
        "txt": f"{nombre_base}.txt",
        "srt": f"{nombre_base}.srt",
        "vtt": f"{nombre_base}.vtt",
        "tsv": f"{nombre_base}.tsv",
        "json": f"{nombre_base}.json"
    }

    ruta_txt = OUTPUT_DIR / archivos["txt"]

    disponible = esperar_archivo(ruta_txt)

    if not disponible:
        raise HTTPException(
            status_code=500,
            detail={
                "mensaje": "La transcripción terminó pero el TXT no apareció",
                "esperado": archivos["txt"],
                "archivos_en_output": [
                    f.name for f in OUTPUT_DIR.glob("*")
                ]
            }
        )

    existencia = {
        formato: (OUTPUT_DIR / nombre).exists()
        for formato, nombre in archivos.items()
    }

    git_resultados = sincronizar_git()

    return {
        "ok": True,
        "archivo_entrada": file.filename,
        "tamano_bytes": total_bytes,
        "archivo_base": nombre_base,
        "archivos_generados": archivos,
        "existencia": existencia,
        "url_txt": f"/transcripcion/{archivos['txt']}",
        "url_descarga_txt": f"/descargar/{archivos['txt']}",
        "url_descarga_srt": f"/descargar/{archivos['srt']}",
        "git": git_resultados
    }


app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")
