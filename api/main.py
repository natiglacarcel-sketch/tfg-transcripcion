from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import subprocess
from typing import Dict

app = FastAPI(
    title="Servidor de Transcripción TFG",
    version="1.0.0",
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
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB


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


def sincronizar_git() -> Dict:
    resultados = {}

    add_result = ejecutar_comando(
        ["git", "add", "data/input", "data/output"],
        cwd=BASE_DIR
    )
    resultados["git_add"] = {
        "returncode": add_result.returncode,
        "stdout": add_result.stdout.strip(),
        "stderr": add_result.stderr.strip()
    }

    commit_result = ejecutar_comando(
        ["git", "commit", "-m", "Añadidos audio y transcripción automática desde API"],
        cwd=BASE_DIR
    )
    resultados["git_commit"] = {
        "returncode": commit_result.returncode,
        "stdout": commit_result.stdout.strip(),
        "stderr": commit_result.stderr.strip()
    }

    push_result = ejecutar_comando(
        ["git", "push"],
        cwd=BASE_DIR
    )
    resultados["git_push"] = {
        "returncode": push_result.returncode,
        "stdout": push_result.stdout.strip(),
        "stderr": push_result.stderr.strip()
    }

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
    ruta_txt = OUTPUT_DIR / nombre

    if not ruta_txt.exists() or not ruta_txt.is_file():
        raise HTTPException(status_code=404, detail="Transcripción no encontrada")

    return ruta_txt.read_text(encoding="utf-8")


@app.get("/descargar/{nombre}")
def descargar_archivo(nombre: str):
    ruta = OUTPUT_DIR / nombre

    if not ruta.exists() or not ruta.is_file():
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
            detail=f"Extensión no permitida. Formatos admitidos: {sorted(ALLOWED_EXTENSIONS)}"
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
                if destino.exists():
                    destino.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"Archivo demasiado grande. Límite: {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB"
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
                "mensaje": "Error durante la transcripción",
                "stderr": resultado.stderr.strip(),
                "stdout": resultado.stdout.strip()
            }
        )

    nombre_base = Path(file.filename).stem

    archivos_generados = {
        "txt": f"{nombre_base}.txt",
        "srt": f"{nombre_base}.srt",
        "vtt": f"{nombre_base}.vtt",
        "tsv": f"{nombre_base}.tsv",
        "json": f"{nombre_base}.json",
    }

    existencia = {
        formato: (OUTPUT_DIR / nombre_archivo).exists()
        for formato, nombre_archivo in archivos_generados.items()
    }

    if not existencia["txt"]:
        raise HTTPException(
            status_code=500,
            detail={
                "mensaje": "La transcripción terminó pero no se encontró el archivo TXT de salida",
                "esperado": archivos_generados["txt"],
                "archivos_en_output": [f.name for f in OUTPUT_DIR.glob("*") if f.is_file()]
            }
        )

    git_resultados = sincronizar_git()

    return {
        "ok": True,
        "archivo_entrada": file.filename,
        "tamano_bytes": total_bytes,
        "archivo_base": nombre_base,
        "archivos_generados": archivos_generados,
        "existencia": existencia,
        "url_txt": f"/transcripcion/{archivos_generados['txt']}",
        "url_descarga_txt": f"/descargar/{archivos_generados['txt']}",
        "url_descarga_srt": f"/descargar/{archivos_generados['srt']}",
        "git": git_resultados
    }


app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")
