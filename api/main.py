from fastapi import FastAPI, UploadFile, File, HTTPException
from pathlib import Path
import shutil
import subprocess

app = FastAPI(title="Servidor de Transcripción TFG")

BASE_DIR = Path("/app")
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"


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


@app.post("/transcribir")
def transcribir(file: UploadFile = File(...)):

    if not file.filename:
        raise HTTPException(status_code=400, detail="Archivo inválido")

    destino = INPUT_DIR / file.filename

    # guardar archivo subido
    with destino.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # comando de transcripción
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

    return {
        "ok": True,
        "archivo_entrada": file.filename,
        "archivo_salida": salida_txt.name,
        "existe_salida": salida_txt.exists()
    }
