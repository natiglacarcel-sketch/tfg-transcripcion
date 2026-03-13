from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import PlainTextResponse
from pathlib import Path
import shutil
import subprocess

app = FastAPI(title="Servidor de Transcripción TFG")

BASE_DIR = Path("/app")
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"


def ejecutar_comando(comando, cwd=None):
    resultado = subprocess.run(
        comando,
        cwd=cwd,
        capture_output=True,
        text=True
    )
    return resultado


def sincronizar_git():
    resultados = {}

    add_result = ejecutar_comando(["git", "add", "data/input", "data/output"], cwd=BASE_DIR)
    resultados["git_add"] = {
        "returncode": add_result.returncode,
        "stderr": add_result.stderr.strip()
    }

    commit_result = ejecutar_comando(
        ["git", "commit", "-m", "Añadida transcripción automática desde API"],
        cwd=BASE_DIR
    )
    resultados["git_commit"] = {
        "returncode": commit_result.returncode,
        "stdout": commit_result.stdout.strip(),
        "stderr": commit_result.stderr.strip()
    }

    # Si no hay cambios, git commit devuelve errorcode != 0, pero no es crítico
    push_result = ejecutar_comando(["git", "push"], cwd=BASE_DIR)
    resultados["git_push"] = {
        "returncode": push_result.returncode,
        "stdout": push_result.stdout.strip(),
        "stderr": push_result.stderr.strip()
    }

    return resultados


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
        "input_files": input_files,
        "output_files": output_files
    }


@app.get("/transcripcion/{nombre}", response_class=PlainTextResponse)
def ver_transcripcion(nombre: str):
    ruta_txt = OUTPUT_DIR / nombre

    if not ruta_txt.exists() or not ruta_txt.is_file():
        raise HTTPException(status_code=404, detail="Transcripción no encontrada")

    return ruta_txt.read_text(encoding="utf-8")


@app.post("/transcribir")
def transcribir(file: UploadFile = File(...)):

    if not file.filename:
        raise HTTPException(status_code=400, detail="Archivo inválido")

    destino = INPUT_DIR / file.filename

    with destino.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    comando = [
    "docker", "run", "--rm",
    "-v", f"{BASE_DIR}:/srv/files:Z",
    "whisper-local",
    f"/srv/files/data/input/{file.filename}",
    "--output_dir", "/srv/files/data/output",
    "--language", "es",
    "--model", "small",
    "--compute_type", "int8"
]

    resultado = subprocess.run(comando, capture_output=True, text=True)

    if resultado.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "mensaje": "Error durante la transcripción",
                "stderr": resultado.stderr
            }
        )

    nombre_sin_ext = Path(file.filename).stem
    salida_txt = OUTPUT_DIR / f"{nombre_sin_ext}.txt"

    if not salida_txt.exists():
        raise HTTPException(
            status_code=500,
            detail="La transcripción terminó pero no se encontró el archivo de salida"
        )

    git_resultados = sincronizar_git()

    return {
        "ok": True,
        "archivo_entrada": file.filename,
        "archivo_salida": salida_txt.name,
        "existe_salida": salida_txt.exists(),
        "url_transcripcion": f"/transcripcion/{salida_txt.name}",
        "git": git_resultados
    }
